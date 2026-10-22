#!/usr/bin/env bash
# Run swarmbench on a Google Cloud ARM (Axion) VM. Run this on your Mac; it needs the gcloud CLI,
# logged in (`gcloud auth login`). The VM has no public IP: SSH goes through IAP, and OS Login
# gives you sudo on it, so no SSH key or firewall rule is managed here.
#
#   deploy/gcp.sh launch [--type n4a-standard-48] [--claude] [--copy-claude-settings]
#                        [--copy-env] [--disk GB] [--public-ip] [--yes] [--print]
#   deploy/gcp.sh ssh | status | stop | start | delete | sync | view
#   deploy/gcp.sh keep-alive on|off|status   (on: never stops by itself; off: idle and uptime stops back)
#   deploy/gcp.sh fetch [RUN_ID ...] [--no-workspace]
#   Every command also takes --name N, --zone Z and --project P. Without --zone, launch uses
#   us-central1-a and the other commands use the zone the VM is in.
#   (fetch: copy runs from the VM's runs/ into this repo's runs/: all of them, or the ones named.
#    Nothing is deleted on either side, and running it again copies only what changed, so it is
#    safe while runs are going. --no-workspace skips the workspace snapshots, the bulkiest part.)
#   (view: forward the VM's Inspect view port to http://localhost:7575 until you press Ctrl-C.)
#   (--print: show the gcloud commands launch, stop, start or delete would run, and run nothing.)
#
# --type is any ARM machine type (N4A, C4A or T2A). N4A sizes (vCPU / memory; agents at once
# across all parallel runs, by memory):
#   n4a-standard-16   16 vCPU   64 GB   up to ~20 agents
#   n4a-standard-32   32 vCPU  128 GB   up to ~40 agents
#   n4a-standard-48   48 vCPU  192 GB   up to ~60 agents   (default)
#   n4a-standard-64   64 vCPU  256 GB   up to ~64 agents
# Prices aren't listed here: check the Compute Engine pricing page for your region. A stopped VM
# costs only its disk; `delete` removes the VM and its disk.
#
# launch options:
#   --claude                 also install Claude Code and the Codex CLI on the VM (for Remote Control)
#   --copy-claude-settings   copy your ~/.claude settings, hooks, skills and this project's memory
#   --copy-env               copy this repo's .env (your API keys) to the VM
#   --idle-minutes N         the VM stops itself N minutes after its last swarmbench run, screen or
#                            judge and its last typing (default 120; 0 = never).
#   --max-uptime-hours H     the VM also stops itself H hours after each start, busy or not
#                            (default 24; 0 = no limit). Both live in /etc/vm-idle-stop on the VM.
#                            Google Cloud also enforces H itself (max run duration), as a backstop
#                            in case the VM can't stop itself.
#   --public-ip              give the VM a public IP (SSH still goes through IAP)
#   --keep-alive             never stop by itself (same as --idle-minutes 0 --max-uptime-hours 0):
#                            it runs, and bills, until you stop it. Holds capacity through stockouts.
# Prerequisites the project's administrators provide: a firewall rule letting IAP reach port 22 on
# VMs tagged iap-ssh, outbound internet for VMs without a public IP (Cloud NAT) so setup can
# download packages, and OS Login sudo for your account. The script checks none of these; setup
# fails with a download error if outbound access is missing.
# The agents' containers have no network.
set -euo pipefail

CMD="${1:-}"; shift || true
PROJECT="${GCP_PROJECT:-kirk-souly-c11-vm}"
DEFAULT_ZONE=us-central1-a
ZONE="${GCP_ZONE:-}"
NAME="${GCP_VM_NAME:-niall-dev}"
TYPE=n4a-standard-48
DISK=250
DISK_TYPE=hyperdisk-balanced
IMAGE_FAMILY=ubuntu-2404-lts-arm64
IMAGE_PROJECT=ubuntu-os-cloud
SERVICE_ACCOUNT="${GCP_SERVICE_ACCOUNT:-vm-runtime-sa@kirk-souly-c11-vm.iam.gserviceaccount.com}"
NETWORK_TAG=iap-ssh
WITH_CLAUDE=0
COPY_SETTINGS=0
COPY_ENV=0
PUBLIC_IP=0
IDLE_MINUTES=120
MAX_UPTIME_HOURS=24
YES=0
PRINT=0
NO_WORKSPACE=0
RUNS=()
KEEP_ARG=""
RSH_ARGS=()
if [ "$CMD" = _rsh ]; then
  RSH_ARGS=("$@"); set --  # rsync's remote shell: host, then the remote command (see below)
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE="$2"; shift 2 ;;
    --zone) ZONE="$2"; shift 2 ;;
    --project) PROJECT="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --disk) DISK="$2"; shift 2 ;;
    --claude) WITH_CLAUDE=1; shift ;;
    --copy-claude-settings) COPY_SETTINGS=1; shift ;;
    --copy-env) COPY_ENV=1; shift ;;
    --public-ip) PUBLIC_IP=1; shift ;;
    --keep-alive) IDLE_MINUTES=0; MAX_UPTIME_HOURS=0; shift ;;
    --idle-minutes)
      [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "--idle-minutes needs a number" >&2; exit 2; }
      IDLE_MINUTES="$2"; shift 2 ;;
    --max-uptime-hours)
      [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "--max-uptime-hours needs a number" >&2; exit 2; }
      MAX_UPTIME_HOURS="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --print) PRINT=1; shift ;;
    --no-workspace) NO_WORKSPACE=1; shift ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    on|off|status)
      [ "$CMD" = keep-alive ] || { echo "unexpected argument: $1" >&2; exit 2; }
      KEEP_ARG="$1"; shift ;;
    *)
      [ "$CMD" = fetch ] || { echo "unexpected argument: $1" >&2; exit 2; }
      [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "not a run id: $1" >&2; exit 2; }
      RUNS+=("$1"); shift ;;
  esac
done
[[ "$NAME" =~ ^[a-z]([-a-z0-9]*[a-z0-9])?$ ]] || { echo "not a valid VM name: $NAME" >&2; exit 2; }

REPO="$(cd "$(dirname "$0")/.." && pwd)"
case "$REPO" in *[[:space:]]*) echo "The repo path has a space in it, which rsync's remote shell can't handle: $REPO" >&2; exit 2 ;; esac
SELF="$REPO/deploy/gcp.sh"
G=(gcloud --project "$PROJECT")
if [ -z "$ZONE" ]; then
  # launch uses the default zone; every other command finds the zone the VM is in, so a VM
  # created elsewhere (e.g. after a stockout) needs no --zone
  if [ "$CMD" != launch ] && [ "$PRINT" != 1 ] && command -v gcloud >/dev/null; then
    ZONE="$("${G[@]}" compute instances list --filter="name=$NAME" --format='value(zone.basename())' 2>/dev/null | head -1 || true)"
  fi
  ZONE="${ZONE:-$DEFAULT_ZONE}"
fi
IAP=(--zone "$ZONE" --tunnel-through-iap --quiet)
# rsync and copy-claude-settings.sh reach the VM through this script ("_rsh"), since IAP needs
# gcloud in the middle. The zone and project travel in the environment.
RSH="env GCP_PROJECT=$PROJECT GCP_ZONE=$ZONE $SELF _rsh"
say() { printf '\n==> %s\n' "$*"; }
# rsync over the IAP tunnel, which can stall on large files: resume partial files, give up on a
# stalled transfer after a minute, and try again (up to 5 times).
rsync_iap() {
  local i
  for i in 1 2 3 4 5; do
    rsync --partial --timeout=60 "$@" && return 0
    echo "rsync stalled or failed (try $i of 5); retrying..." >&2
  done
  return 1
}

# Run a gcloud command that changes something, or with --print only show it.
change() {
  if [ "$PRINT" = 1 ]; then
    printf '+'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

need_gcloud() {
  [ "$PRINT" = 1 ] && return 0
  command -v gcloud >/dev/null || { echo "Install the gcloud CLI first: brew install --cask google-cloud-sdk" >&2; exit 1; }
  [ -n "$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null)" ] \
    || { echo "gcloud isn't logged in: gcloud auth login" >&2; exit 1; }
}

vm_status() {
  [ "$PRINT" = 1 ] && return 0
  "${G[@]}" compute instances describe "$NAME" --zone "$ZONE" --format='value(status)' 2>/dev/null || true
}

ours() {
  # Only VMs this script created (label swarmbench=1) may be stopped, started, synced or deleted
  [ "$("${G[@]}" compute instances describe "$NAME" --zone "$ZONE" --format='value(labels.swarmbench)' 2>/dev/null || true)" = 1 ]
}

ssh_to() { "${G[@]}" compute ssh "$NAME" "${IAP[@]}" -- "$@"; }

sync_repo() {
  # Tracked and untracked files (e.g. new scenarios), minus everything git ignores (.env, runs/,
  # .venv, build output), as listed by git itself. (rsync's own .gitignore parsing reads a "!"
  # line as "clear all excludes", which would copy .env.) Then the git history, so commits work
  # on the VM. Files deleted on the Mac are not deleted on the VM.
  local list
  list="$(mktemp)"
  git -C "$REPO" ls-files -co --exclude-standard -z >"$list"
  if tr '\0' '\n' <"$list" | grep -E '(^|/)\.env$' >/dev/null; then
    echo "Refusing to sync: git would include a .env file." >&2; rm "$list"; exit 1
  fi
  rsync_iap -az --from0 --files-from="$list" -e "$RSH" "$REPO/" "$NAME:swarmbench/"
  rsync_iap -az -e "$RSH" "$REPO/.git/" "$NAME:swarmbench/.git/"
  rm "$list"
}

fetch_runs() {
  # The VM's runs/ into this repo's runs/, without --delete: nothing local is ever removed. The
  # VM's run index (runs.jsonl, RUNS.md) is left out: the local one is rebuilt by `swarm list`.
  local opts=(-az -e "$RSH") r
  [ "$NO_WORKSPACE" = 1 ] && opts+=(--exclude '*.tar.gz')  # the start/end workspace snapshots
  mkdir -p "$REPO/runs"
  if [ ${#RUNS[@]} -eq 0 ]; then
    rsync_iap "${opts[@]}" --exclude '/runs.jsonl' --exclude '/RUNS.md' "$NAME:swarmbench/runs/" "$REPO/runs/"
  else
    for r in "${RUNS[@]}"; do
      rsync_iap "${opts[@]}" "$NAME:swarmbench/runs/$r" "$REPO/runs/"
    done
  fi
  echo "Copied into $REPO/runs/. See them with: uv run swarm list"
}

create_vm() {
  local args=(
    "${G[@]}" compute instances create "$NAME"
    --zone "$ZONE"
    --machine-type "$TYPE"
    --image-family "$IMAGE_FAMILY" --image-project "$IMAGE_PROJECT"
    --boot-disk-type "$DISK_TYPE" --boot-disk-size "${DISK}GB"
    --service-account "$SERVICE_ACCOUNT" --scopes cloud-platform
    --tags "$NETWORK_TAG"
    --labels swarmbench=1
    --metadata enable-oslogin=TRUE
  )
  [ "$PUBLIC_IP" = 1 ] || args+=(--no-address)
  if [ "$MAX_UPTIME_HOURS" -gt 0 ]; then
    # Google Cloud's own backstop: it stops the VM after this long, even if the VM can't
    args+=(--max-run-duration "${MAX_UPTIME_HOURS}h" --instance-termination-action STOP)
  fi
  change "${args[@]}"
}

launch() {
  need_gcloud
  if [ -n "$(vm_status)" ]; then
    echo "A VM named '$NAME' already exists in $ZONE ($(vm_status)). Use --name, or: $0 start" >&2
    exit 1
  fi
  if [ "$PRINT" != 1 ]; then
    local arch
    arch="$("${G[@]}" compute machine-types describe "$TYPE" --zone "$ZONE" --format='value(architecture)' 2>/dev/null || true)"
    case "$arch" in
      ARM64) ;;
      "") echo "Unknown machine type '$TYPE' in $ZONE." >&2; exit 2 ;;
      *) echo "$TYPE isn't an ARM machine type ($arch); use an N4A, C4A or T2A type." >&2; exit 2 ;;
    esac
  fi
  echo "Launching $TYPE in $ZONE (project $PROJECT), ${DISK} GB $DISK_TYPE disk," \
       "$([ "$PUBLIC_IP" = 1 ] && echo "with a public IP" || echo "no public IP")."
  echo "Options: claude=$WITH_CLAUDE copy-claude-settings=$COPY_SETTINGS copy-env=$COPY_ENV" \
       "idle-minutes=$IDLE_MINUTES max-uptime-hours=$MAX_UPTIME_HOURS"
  if [ "$MAX_UPTIME_HOURS" = 0 ] && [ "$IDLE_MINUTES" = 0 ]; then
    echo "WARNING: keep-alive: the VM never stops by itself. It runs, and bills, until you stop it" \
         "($0 stop) or turn keep-alive off ($0 keep-alive off)." >&2
  elif [ "$MAX_UPTIME_HOURS" = 0 ]; then
    echo "WARNING: --max-uptime-hours 0 also turns off Google's own run-time limit, the only stop that" \
         "works if the VM itself is stuck. Only the VM's idle stop (installed by setup) remains." >&2
  fi
  if [ "$PRINT" = 1 ]; then
    create_vm
    echo "(--print: nothing was run. After creating it, launch copies the repo over IAP, runs" \
         "deploy/bootstrap.sh on the VM, and optionally copies .env and your Claude settings.)"
    return 0
  fi
  if [ "$YES" != 1 ]; then
    read -r -p "Launch? [y/N] " ok
    [ "$ok" = y ] || [ "$ok" = Y ] || exit 1
  fi

  say "VM"
  create_vm

  say "Waiting for SSH (through IAP; the first time, gcloud also sets up your OS Login key)"
  local up=0
  for _ in $(seq 60); do ssh_to true 2>/dev/null && { up=1; break; }; sleep 5; done
  [ "$up" = 1 ] || { echo "Couldn't reach the VM over IAP. Try: $0 ssh" >&2; exit 1; }

  say "Copying the repo"
  sync_repo
  if [ "$COPY_ENV" = 1 ]; then
    if [ -f "$REPO/.env" ]; then
      # streamed into a file created private (umask 077), so it is never readable by others
      ssh_to 'umask 077 && cat > swarmbench/.env.tmp && chmod 600 swarmbench/.env.tmp && mv swarmbench/.env.tmp swarmbench/.env' <"$REPO/.env"
      echo "Copied .env"
    else
      echo "No .env in $REPO, nothing to copy."
    fi
  fi

  say "Setting up the VM (Docker, uv, image build, Docker tests, dry run: about 10-15 minutes)"
  local setup_ok=1
  ssh_to "bash swarmbench/deploy/bootstrap.sh --idle-minutes $IDLE_MINUTES --max-uptime-hours $MAX_UPTIME_HOURS $([ "$WITH_CLAUDE" = 1 ] && echo --claude)" || setup_ok=0
  [ "$setup_ok" = 1 ] || echo "WARNING: the VM's setup failed (see above); fix it, then rerun: bash swarmbench/deploy/bootstrap.sh" >&2
  if ! ssh_to systemctl is-active --quiet vm-idle-stop.timer; then
    echo "WARNING: the VM's idle stop isn't running; stop the VM yourself when done ($0 stop)." >&2
  fi
  [ "$setup_ok" = 1 ] || exit 1

  if [ "$COPY_SETTINGS" = 1 ]; then
    say "Copying your Claude settings"
    local home
    home="$(ssh_to 'printf %s "$HOME"')"
    "$REPO/deploy/copy-claude-settings.sh" "$NAME" --rsh "$RSH" --repo-path "$home/swarmbench"
  fi

  say "Ready"
  cat <<EOF
  $0 ssh                  (or: gcloud compute ssh $NAME --zone $ZONE --tunnel-through-iap)
  Stop it when idle:  $0 stop   (delete it and its disk: $0 delete)
  It stops itself $IDLE_MINUTES minutes after work ends, and $MAX_UPTIME_HOURS hours after each start
  (0 = off; change in /etc/vm-idle-stop on the VM).
  Copy new local changes over:  $0 sync
  Copy runs back to the Mac:    $0 fetch [RUN_ID ...]   (before deleting!)
  Inspect view from the Mac:    $0 view     then on the VM: uv run swarm view runs/<id>
                                and open http://localhost:7575
EOF
}

with_vm() {
  need_gcloud
  [ "$PRINT" = 1 ] && return 0
  [ -n "$(vm_status)" ] || { echo "No VM named '$NAME' in $ZONE (project $PROJECT)." >&2; exit 1; }
  ours || { echo "The VM '$NAME' wasn't created by this script (no swarmbench=1 label); refusing to touch it." >&2; exit 1; }
}

case "$CMD" in
  _rsh)
    # rsync calls this as: gcp.sh _rsh <host> <remote command...>; the host is the VM's name
    host="${RSH_ARGS[0]:?}"
    # no terminal (-T): gcloud asks for one by default, which stalls rsync's data stream
    exec "${G[@]}" compute ssh "$host" "${IAP[@]}" --ssh-flag=-T -- "${RSH_ARGS[@]:1}" ;;
  launch) launch ;;
  ssh) with_vm; exec "${G[@]}" compute ssh "$NAME" "${IAP[@]}" ;;
  status)
    with_vm
    "${G[@]}" compute instances describe "$NAME" --zone "$ZONE" \
      --format='table(name,machineType.basename(),status,networkInterfaces[0].networkIP)' ;;
  stop)
    with_vm
    change "${G[@]}" compute instances stop "$NAME" --zone "$ZONE" --quiet
    [ "$PRINT" = 1 ] || echo "Stopped $NAME (its disk is kept)." ;;
  start)
    with_vm
    change "${G[@]}" compute instances start "$NAME" --zone "$ZONE" --quiet
    [ "$PRINT" = 1 ] || echo "Started $NAME." ;;
  delete)
    with_vm
    if [ "$YES" != 1 ] && [ "$PRINT" != 1 ]; then
      read -r -p "Delete $NAME and its disk, including any runs/ not copied back ($0 fetch)? [y/N] " ok
      [ "$ok" = y ] || [ "$ok" = Y ] || exit 1
    fi
    change "${G[@]}" compute instances delete "$NAME" --zone "$ZONE" --delete-disks=all --quiet ;;
  sync) with_vm; sync_repo; echo "Synced." ;;
  fetch) with_vm; fetch_runs ;;
  keep-alive)
    with_vm
    case "$KEEP_ARG" in
      on) idle=0; uptime=0 ;;
      off) idle=$IDLE_MINUTES; uptime=$MAX_UPTIME_HOURS
           [ "$idle" = 0 ] && idle=120; [ "$uptime" = 0 ] && uptime=24 ;;
      status|"") ssh_to 'cat /etc/vm-idle-stop'; exit 0 ;;
    esac
    if [ "$PRINT" = 1 ]; then
      echo "+ on the VM: IDLE_MINUTES=$idle MAX_UPTIME_HOURS=$uptime in /etc/vm-idle-stop"; exit 0
    fi
    [ "$(vm_status)" = RUNNING ] || { echo "The VM isn't running; start it first ($0 start)." >&2; exit 1; }
    ssh_to "printf 'IDLE_MINUTES=$idle\\nMAX_UPTIME_HOURS=$uptime\\n' | sudo tee /etc/vm-idle-stop >/dev/null && cat /etc/vm-idle-stop"
    if [ "$KEEP_ARG" = on ]; then
      limit="$("${G[@]}" compute instances describe "$NAME" --zone "$ZONE" --format='value(scheduling.maxRunDuration.seconds)' 2>/dev/null || true)"
      [ -z "$limit" ] || echo "Note: Google's own run limit (${limit}s) is still set; it can only be removed while the VM is stopped: gcloud compute instances set-scheduling $NAME --zone $ZONE --clear-max-run-duration" >&2
      echo "Keep-alive is on: the VM runs, and bills, until you stop it ($0 stop) or turn this off ($0 keep-alive off)."
    else
      echo "Keep-alive is off: it stops $idle minutes after work ends, and $uptime hours after each start."
    fi ;;
  view)
    with_vm
    echo "Forwarding http://localhost:7575 to the VM; press Ctrl-C to stop."
    exec "${G[@]}" compute ssh "$NAME" "${IAP[@]}" -- -N -L 7575:localhost:7575 ;;
  *) sed -n 2,40p "$0"; exit 2 ;;
esac
