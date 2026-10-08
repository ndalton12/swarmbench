#!/usr/bin/env bash
# Run swarmbench on an AWS Graviton (ARM) VM. Run this on your Mac; it needs the AWS CLI v2,
# logged in (`aws configure` or `aws sso login`).
#
#   deploy/aws.sh launch [--size small|medium|large|xlarge] [--claude] [--copy-claude-settings]
#                        [--copy-env] [--region R] [--name N] [--disk GB] [--yes]
#   deploy/aws.sh ssh | status | stop | start | terminate | allow-my-ip | sync   [--name N] [--region R]
#   (allow-my-ip: SSH from your current IP only; any previously allowed IP is removed)
#
# Sizes (agents running at the same time, across all parallel runs):
#   small   m7g.2xlarge    8 vCPU   32 GB   up to ~8 agents    about $0.33/hour
#   medium  m7g.4xlarge   16 vCPU   64 GB   up to ~20 agents   about $0.65/hour   (default)
#   large   m7g.8xlarge   32 vCPU  128 GB   up to ~40 agents   about $1.31/hour
#   xlarge  m7g.16xlarge  64 vCPU  256 GB   up to ~64 agents   about $2.61/hour
# Prices are us-east-1 on-demand list prices, checked October 2026; other regions differ.
# A stopped VM costs only its disk (about $0.08 per GB-month); terminate it to stop all charges.
#
# launch options:
#   --claude                 also install Claude Code and the Codex CLI on the VM (for Remote Control)
#   --copy-claude-settings   copy your ~/.claude settings, hooks, skills and this project's memory
#   --copy-env               copy this repo's .env (your API keys) to the VM
# The VM accepts SSH only from your current IP address. The agents' containers have no network.
set -euo pipefail

CMD="${1:-}"; shift || true
SIZE=medium
REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
REGION="${REGION:-us-east-1}"
NAME=swarmbench
DISK=200
WITH_CLAUDE=0
COPY_SETTINGS=0
COPY_ENV=0
YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --size) SIZE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --disk) DISK="$2"; shift 2 ;;
    --claude) WITH_CLAUDE=1; shift ;;
    --copy-claude-settings) COPY_SETTINGS=1; shift ;;
    --copy-env) COPY_ENV=1; shift ;;
    --yes|-y) YES=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$SIZE" in
  small) TYPE=m7g.2xlarge; PRICE=0.33 ;;
  medium) TYPE=m7g.4xlarge; PRICE=0.65 ;;
  large) TYPE=m7g.8xlarge; PRICE=1.31 ;;
  xlarge) TYPE=m7g.16xlarge; PRICE=2.61 ;;
  *) echo "--size must be small, medium, large or xlarge" >&2; exit 2 ;;
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

launch() {
  need_aws
  if [ -n "$(instance_id)" ]; then
    echo "An instance named '$NAME' already exists in $REGION ($(instance_id)). Use --name, or: $0 start" >&2
    exit 1
  fi
  echo "Launching $TYPE ($SIZE) in $REGION, ${DISK} GB disk: about \$$PRICE/hour while running."
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
        --metadata-options HttpTokens=required \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=swarmbench,Value=1}]" \
        --query 'Instances[0].InstanceId' --output text)"
  echo "$id"
  "${AWS[@]}" ec2 wait instance-running --instance-ids "$id"
  ip="$(public_ip "$id")"
  echo "Public IP: $ip"

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
  ssh_to "$ip" "bash swarmbench/deploy/bootstrap.sh $([ "$WITH_CLAUDE" = 1 ] && echo --claude)"

  if [ "$COPY_SETTINGS" = 1 ]; then
    say "Copying your Claude settings"
    "$REPO/deploy/copy-claude-settings.sh" "$USER_AT@$ip" -i "$KEY_FILE" --repo-path "/home/$USER_AT/swarmbench"
  fi

  say "Ready"
  cat <<EOF
  ssh -i $KEY_FILE $USER_AT@$ip        (or: $0 ssh)
  Running: about \$$PRICE/hour. Stop it when idle:  $0 stop   (terminate to delete it: $0 terminate)
  Copy new local changes over:  $0 sync
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
      read -r -p "Terminate $ID and DELETE its disk, including any runs/ not copied back? [y/N] " ok
      [ "$ok" = y ] || [ "$ok" = Y ] || exit 1
    fi
    "${AWS[@]}" ec2 terminate-instances --instance-ids "$ID" >/dev/null; echo "Terminating $ID." ;;
  allow-my-ip) need_aws; allow_my_ip ;;
  sync) with_instance; sync_repo "$(public_ip "$ID")"; echo "Synced." ;;
  *) sed -n 2,22p "$0"; exit 2 ;;
esac
