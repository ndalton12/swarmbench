#!/usr/bin/env bash
# Run swarmbench on an AWS Graviton (ARM) VM. Run this on your Mac; it needs the AWS CLI v2,
# logged in (`aws configure` or `aws sso login`).
#
#   deploy/aws.sh launch [--type m7g.4xlarge] [--claude] [--copy-claude-settings]
#                        [--copy-env] [--region R] [--name N] [--disk GB] [--yes]
#   deploy/aws.sh ssh | status | stop | start | terminate | allow-my-ip | sync   [--name N] [--region R]
#   deploy/aws.sh fetch [RUN_ID ...] [--no-workspace]   [--name N] [--region R]
#   (allow-my-ip: SSH from your current IP only; any previously allowed IP is removed)
#   (fetch: copy runs from the VM's runs/ into this repo's runs/: all of them, or the ones named.
#    Nothing is deleted on either side, and running it again copies only what changed, so it is
#    safe while runs are going. --no-workspace skips the workspace snapshots, the bulkiest part.)
#
# --type is any ARM (Graviton) instance type. Suggested (agents running at the same time,
# across all parallel runs):
#   m7g.2xlarge    8 vCPU   32 GB   up to ~8 agents    about $0.33/hour
#   m7g.4xlarge   16 vCPU   64 GB   up to ~20 agents   about $0.65/hour   (default)
#   m7g.8xlarge   32 vCPU  128 GB   up to ~40 agents   about $1.31/hour
#   m7g.16xlarge  64 vCPU  256 GB   up to ~64 agents   about $2.61/hour
# Prices are us-east-1 on-demand list prices, checked October 2026; other regions differ.
# Other types work too (e.g. c7g/r7g/m8g); their price isn't shown, so check it first.
# A stopped VM costs only its disk (about $0.08 per GB-month); terminate it to stop all charges.
#
# launch options:
#   --claude                 also install Claude Code and the Codex CLI on the VM (for Remote Control)
#   --copy-claude-settings   copy your ~/.claude settings, hooks, skills and this project's memory
#   --copy-env               copy this repo's .env (your API keys) to the VM
#   --idle-minutes N         the VM stops itself N minutes after its last swarmbench run, screen or
#                            judge and its last typing (default 120; 0 = never). As a backstop, a
#                            CloudWatch alarm also stops it after 6 hours of almost no network traffic.
#   --max-uptime-hours H     the VM also stops itself H hours after each start, busy or not
#                            (default 24; 0 = no limit). Both live in /etc/vm-idle-stop on the VM.
# The VM accepts SSH only from your current IP address. The agents' containers have no network.
set -euo pipefail

CMD="${1:-}"; shift || true
TYPE=m7g.4xlarge
REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
REGION="${REGION:-us-east-1}"
NAME=swarmbench
DISK=200
WITH_CLAUDE=0
COPY_SETTINGS=0
COPY_ENV=0
IDLE_MINUTES=120
MAX_UPTIME_HOURS=24
YES=0
NO_WORKSPACE=0
RUNS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --disk) DISK="$2"; shift 2 ;;
    --claude) WITH_CLAUDE=1; shift ;;
    --copy-claude-settings) COPY_SETTINGS=1; shift ;;
    --copy-env) COPY_ENV=1; shift ;;
    --idle-minutes)
      [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "--idle-minutes needs a number" >&2; exit 2; }
      IDLE_MINUTES="$2"; shift 2 ;;
    --max-uptime-hours)
      [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "--max-uptime-hours needs a number" >&2; exit 2; }
      MAX_UPTIME_HOURS="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --no-workspace) NO_WORKSPACE=1; shift ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *)
      [ "$CMD" = fetch ] || { echo "unexpected argument: $1" >&2; exit 2; }
      [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "not a run id: $1" >&2; exit 2; }
      RUNS+=("$1"); shift ;;
  esac
done

case "$TYPE" in
  m7g.2xlarge) PRICE='about $0.33/hour' ;;
  m7g.4xlarge) PRICE='about $0.65/hour' ;;
  m7g.8xlarge) PRICE='about $1.31/hour' ;;
  m7g.16xlarge) PRICE='about $2.61/hour' ;;
  *) PRICE='price not known here: check AWS pricing' ;;
esac

REPO="$(cd "$(dirname "$0")/.." && pwd)"
KEY_NAME="swarmbench-$REGION"
KEY_FILE="$HOME/.ssh/$KEY_NAME.pem"
SG_NAME="swarmbench-ssh"
USER_AT="ubuntu"
AWS=(aws --region "$REGION")
say() { printf '\n==> %s\n' "$*"; }

need_aws() {
  command -v aws >/dev/null || { echo "Install the AWS CLI v2 first: brew install awscli" >&2; exit 1; }
  "${AWS[@]}" sts get-caller-identity >/dev/null || { echo "AWS CLI isn't logged in (aws configure / aws sso login)." >&2; exit 1; }
}

instance_id() {
  "${AWS[@]}" ec2 describe-instances \
    --filters "Name=tag:Name,Values=$NAME" "Name=tag:swarmbench,Values=1" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text
}

public_ip() {
  "${AWS[@]}" ec2 describe-instances --instance-ids "$1" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
}

ssh_to() { ssh -i "$KEY_FILE" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 "$USER_AT@$1" "${@:2}"; }

my_ip() { curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]'; }

security_group() {
  local vpc sg
  vpc="$("${AWS[@]}" ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
  [ "$vpc" != "None" ] || { echo "No default VPC in $REGION; create one (aws ec2 create-default-vpc)." >&2; exit 1; }
  sg="$("${AWS[@]}" ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$vpc" \
        --query 'SecurityGroups[0].GroupId' --output text)"
  if [ "$sg" = "None" ]; then
    sg="$("${AWS[@]}" ec2 create-security-group --group-name "$SG_NAME" --vpc-id "$vpc" \
          --description "swarmbench: SSH from the owner's IP only" --query GroupId --output text)"
  fi
  echo "$sg"
}

allow_my_ip() {
  # Make the group allow exactly one thing: SSH from this machine's current IP. Every other
  # inbound rule (an old IP, or anything wider) is removed first.
  local sg ip current
  sg="$(security_group)"; ip="$(my_ip)"
  [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Couldn't find your public IP (got '$ip')." >&2; exit 1; }
  current="$("${AWS[@]}" ec2 describe-security-groups --group-ids "$sg" --query 'SecurityGroups[0].IpPermissions' --output json)"
  if [ "$current" != "[]" ]; then
    "${AWS[@]}" ec2 revoke-security-group-ingress --group-id "$sg" --ip-permissions "$current" >/dev/null
  fi
  "${AWS[@]}" ec2 authorize-security-group-ingress --group-id "$sg" \
    --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$ip/32,Description=swarmbench-owner}]" >/dev/null
  echo "SSH allowed from $ip only"
}

sync_repo() {
  # Tracked and untracked files (e.g. new scenarios), minus everything git ignores (.env, runs/,
  # .venv, build output), as listed by git itself. (rsync's own .gitignore parsing reads a "!"
  # line as "clear all excludes", which would copy .env.) Then the git history, so commits work
  # on the VM. Files deleted on the Mac are not deleted on the VM.
  local rsh="ssh -i $KEY_FILE -o StrictHostKeyChecking=accept-new" list
  list="$(mktemp)"
  git -C "$REPO" ls-files -co --exclude-standard -z >"$list"
  if tr '\0' '\n' <"$list" | grep -qE '(^|/)\.env$'; then
    echo "Refusing to sync: git would include a .env file." >&2; rm "$list"; exit 1
  fi
  rsync -az --from0 --files-from="$list" -e "$rsh" "$REPO/" "$USER_AT@$1:swarmbench/"
  rsync -az -e "$rsh" "$REPO/.git/" "$USER_AT@$1:swarmbench/.git/"
  rm "$list"
}

fetch_runs() {
  # The VM's runs/ into this repo's runs/, without --delete: nothing local is ever removed. The
  # VM's run index (runs.jsonl, RUNS.md) is left out: the local one is rebuilt by `swarm list`.
  local rsh="ssh -i $KEY_FILE -o StrictHostKeyChecking=accept-new" r
  local opts=(-az -e "$rsh")
  [ "$NO_WORKSPACE" = 1 ] && opts+=(--exclude '*.tar.gz')  # the start/end workspace snapshots
  mkdir -p "$REPO/runs"
  if [ ${#RUNS[@]} -eq 0 ]; then
    rsync "${opts[@]}" --exclude '/runs.jsonl' --exclude '/RUNS.md' "$USER_AT@$1:swarmbench/runs/" "$REPO/runs/"
  else
    for r in "${RUNS[@]}"; do
      rsync "${opts[@]}" "$USER_AT@$1:swarmbench/runs/$r" "$REPO/runs/"
    done
  fi
  echo "Copied into $REPO/runs/. See them with: uv run swarm list"
}

idle_alarm() {
  # A backstop to the VM's own idle stop (deploy/idle-stop.sh), in case the VM can't run it: stop
  # the instance after 6 hours in which every hour sent under 5 MB over the network. CPU can't be
  # used: judging, which waits on model APIs, uses far under 1% of a large VM's CPUs, as idle
  # does; but it sends megabytes of prompts an hour, and a run sends far more.
  [ "$IDLE_MINUTES" -gt 0 ] || { echo "Idle stop is off (--idle-minutes 0): no backstop alarm."; return 0; }
  if "${AWS[@]}" cloudwatch put-metric-alarm --alarm-name "swarmbench-idle-$1" \
    --alarm-description "Stop the swarmbench VM $1 after 6 hours of almost no network traffic" \
    --namespace AWS/EC2 --metric-name NetworkOut --dimensions "Name=InstanceId,Value=$1" \
    --statistic Sum --period 3600 --evaluation-periods 6 --threshold 5000000 \
    --comparison-operator LessThanThreshold --treat-missing-data notBreaching \
    --alarm-actions "arn:aws:automate:$REGION:ec2:stop"; then
    echo "Backstop alarm: stops the VM after 6 hours with under 5 MB/hour of network traffic"
  else
    echo "WARNING: couldn't create the CloudWatch backstop alarm; only the VM's own idle stop will" \
         "protect it. Check the CLI user's permissions (deploy/aws-iam-policy.json)." >&2
  fi
}

launch() {
  need_aws
  if [ -n "$(instance_id)" ]; then
    echo "An instance named '$NAME' already exists in $REGION ($(instance_id)). Use --name, or: $0 start" >&2
    exit 1
  fi
  local arch
  arch="$("${AWS[@]}" ec2 describe-instance-types --instance-types "$TYPE" \
          --query 'InstanceTypes[0].ProcessorInfo.SupportedArchitectures' --output text 2>/dev/null || true)"
  case "$arch" in
    *arm64*) ;;
    "") echo "Unknown instance type '$TYPE' in $REGION." >&2; exit 2 ;;
    *) echo "$TYPE isn't an ARM (Graviton) type; use one ending in g, e.g. m7g.4xlarge." >&2; exit 2 ;;
  esac
  echo "Launching $TYPE in $REGION, ${DISK} GB disk ($PRICE while running)."
  echo "Options: claude=$WITH_CLAUDE copy-claude-settings=$COPY_SETTINGS copy-env=$COPY_ENV"
  if [ "$YES" != 1 ]; then
    read -r -p "Launch? [y/N] " ok
    [ "$ok" = y ] || [ "$ok" = Y ] || exit 1
  fi

  if [ ! -f "$KEY_FILE" ]; then
    say "SSH key pair $KEY_NAME"
    mkdir -p "$HOME/.ssh"
    "${AWS[@]}" ec2 create-key-pair --key-name "$KEY_NAME" --key-type ed25519 \
      --query KeyMaterial --output text >"$KEY_FILE"
    chmod 600 "$KEY_FILE"
  fi

  say "Security group (SSH from your IP only)"
  local sg ami id ip
  sg="$(security_group)"
  allow_my_ip

  ami="$("${AWS[@]}" ssm get-parameter \
    --name /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id \
    --query Parameter.Value --output text)"

  say "Instance"
  id="$("${AWS[@]}" ec2 run-instances --image-id "$ami" --instance-type "$TYPE" \
        --key-name "$KEY_NAME" --security-group-ids "$sg" \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK,VolumeType=gp3,DeleteOnTermination=true}" \
        --metadata-options HttpTokens=required --instance-initiated-shutdown-behavior stop \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=swarmbench,Value=1}]" \
        --query 'Instances[0].InstanceId' --output text)"
  echo "$id"
  "${AWS[@]}" ec2 wait instance-running --instance-ids "$id"
  ip="$(public_ip "$id")"
  echo "Public IP: $ip"
  idle_alarm "$id"

  say "Waiting for SSH"
  for _ in $(seq 60); do ssh_to "$ip" true 2>/dev/null && break; sleep 5; done

  say "Copying the repo"
  sync_repo "$ip"
  if [ "$COPY_ENV" = 1 ]; then
    if [ -f "$REPO/.env" ]; then
      scp -i "$KEY_FILE" -q "$REPO/.env" "$USER_AT@$ip:swarmbench/.env"
      ssh_to "$ip" chmod 600 swarmbench/.env
      echo "Copied .env"
    else
      echo "No .env in $REPO, nothing to copy."
    fi
  fi

  say "Setting up the VM (Docker, uv, image build, Docker tests, dry run: about 10-15 minutes)"
  local setup_ok=1
  ssh_to "$ip" "bash swarmbench/deploy/bootstrap.sh --idle-minutes $IDLE_MINUTES --max-uptime-hours $MAX_UPTIME_HOURS $([ "$WITH_CLAUDE" = 1 ] && echo --claude)" || setup_ok=0
  [ "$setup_ok" = 1 ] || echo "WARNING: the VM's setup failed (see above); fix it, then rerun: bash swarmbench/deploy/bootstrap.sh" >&2
  if ! ssh_to "$ip" systemctl is-active --quiet vm-idle-stop.timer; then
    echo "WARNING: the VM's idle stop isn't running; stop the VM yourself when done ($0 stop)." >&2
  fi
  [ "$setup_ok" = 1 ] || exit 1

  if [ "$COPY_SETTINGS" = 1 ]; then
    say "Copying your Claude settings"
    "$REPO/deploy/copy-claude-settings.sh" "$USER_AT@$ip" -i "$KEY_FILE" --repo-path "/home/$USER_AT/swarmbench"
  fi

  say "Ready"
  cat <<EOF
  ssh -i $KEY_FILE $USER_AT@$ip        (or: $0 ssh)
  Running: $PRICE. Stop it when idle:  $0 stop   (terminate to delete it: $0 terminate)
  It stops itself $IDLE_MINUTES minutes after work ends, and $MAX_UPTIME_HOURS hours after each start
  (0 = off; change in /etc/vm-idle-stop on the VM).
  Copy new local changes over:  $0 sync
  Copy runs back to the Mac:    $0 fetch [RUN_ID ...]   (before terminating!)
  Inspect view from the Mac:    ssh -i $KEY_FILE -L 7575:localhost:7575 $USER_AT@$ip
                                then on the VM: uv run swarm view runs/<id>   and open http://localhost:7575
EOF
}

with_instance() {
  need_aws
  ID="$(instance_id)"
  [ -n "$ID" ] || { echo "No instance named '$NAME' in $REGION." >&2; exit 1; }
}

case "$CMD" in
  launch) launch ;;
  ssh) with_instance; exec ssh -i "$KEY_FILE" -o StrictHostKeyChecking=accept-new "$USER_AT@$(public_ip "$ID")" ;;
  status)
    with_instance
    "${AWS[@]}" ec2 describe-instances --instance-ids "$ID" \
      --query 'Reservations[0].Instances[0].[InstanceId,InstanceType,State.Name,PublicIpAddress]' --output text ;;
  stop) with_instance; "${AWS[@]}" ec2 stop-instances --instance-ids "$ID" >/dev/null; echo "Stopping $ID (disk is kept)." ;;
  start)
    with_instance; allow_my_ip
    "${AWS[@]}" ec2 start-instances --instance-ids "$ID" >/dev/null
    "${AWS[@]}" ec2 wait instance-running --instance-ids "$ID"
    echo "Running at $(public_ip "$ID") (the IP changes after each stop)." ;;
  terminate)
    with_instance
    if [ "$YES" != 1 ]; then
      read -r -p "Terminate $ID and DELETE its disk, including any runs/ not copied back ($0 fetch)? [y/N] " ok
      [ "$ok" = y ] || [ "$ok" = Y ] || exit 1
    fi
    "${AWS[@]}" ec2 terminate-instances --instance-ids "$ID" >/dev/null; echo "Terminating $ID."
    "${AWS[@]}" cloudwatch delete-alarms --alarm-names "swarmbench-idle-$ID" 2>/dev/null || true ;;
  allow-my-ip) need_aws; allow_my_ip ;;
  sync) with_instance; sync_repo "$(public_ip "$ID")"; echo "Synced." ;;
  fetch) with_instance; fetch_runs "$(public_ip "$ID")" ;;
  *) sed -n 2,33p "$0"; exit 2 ;;
esac
