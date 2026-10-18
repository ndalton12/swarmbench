#!/usr/bin/env bash
# Stop this VM once it has been idle for a while, so a forgotten VM doesn't keep billing.
# deploy/bootstrap.sh installs it as /usr/local/sbin/vm-idle-stop with a systemd timer that runs
# it as root every 5 minutes. A stop keeps the disk; `deploy/aws.sh start` brings the VM back.
#
# Busy means either of:
#   - swarmbench working: a run, screen, experiment or judge, attached or detached (`swarm view`
#     doesn't count: a forgotten viewer would keep the VM up forever);
#   - someone typing in a terminal (SSH or tmux) in the last 30 minutes. Only input counts: a
#     terminal's read time, not its write time, so a tmux clock or a chatty program doesn't.
# So the VM stops IDLE_MINUTES after the last work ends, or up to 30 minutes more after the last
# typing. Whatever happens, it also stops MAX_UPTIME_HOURS after it was started, busy or not.
# Settings in /etc/vm-idle-stop: IDLE_MINUTES=120, MAX_UPTIME_HOURS=24 (0 turns each one off).
set -euo pipefail

IDLE_MINUTES=120
MAX_UPTIME_HOURS=24
if [ -f /etc/vm-idle-stop ]; then
  # shellcheck disable=SC1091
  . /etc/vm-idle-stop
fi

stop_vm() {
  logger -t vm-idle-stop "$1; stopping the VM"
  wall "$1: stopping this VM now (the disk is kept; deploy/aws.sh start brings it back)." 2>/dev/null || true
  shutdown -h now
}

uptime_hours=$(( $(cut -d. -f1 /proc/uptime) / 3600 ))
if [ "$MAX_UPTIME_HOURS" -gt 0 ] && [ "$uptime_hours" -ge "$MAX_UPTIME_HOURS" ]; then
  stop_vm "Up for $uptime_hours hours (the limit is MAX_UPTIME_HOURS=$MAX_UPTIME_HOURS in /etc/vm-idle-stop)"
  exit 0
fi
[ "$IDLE_MINUTES" -gt 0 ] || exit 0

# /run is emptied at boot, so a VM that was just started counts as busy from then on
STAMP=/run/vm-idle-stop/last-busy
mkdir -p "$(dirname "$STAMP")"

busy() {
  # detached workers are `python -m swarmbench.cli _worker|_screen|_supervise ...`
  pgrep -f -- 'swarmbench\.cli (_worker|_screen|_supervise|run|screen|experiment|judge)( |$)|/bin/swarm (run|screen|experiment|judge)( |$)' >/dev/null && return 0
  [ -n "$(find /dev/pts -maxdepth 1 -name '[0-9]*' -amin -30 2>/dev/null)" ] && return 0
  return 1
}

if busy || [ ! -f "$STAMP" ]; then
  touch "$STAMP"
  exit 0
fi

idle=$(( ($(date +%s) - $(stat -c %Y "$STAMP")) / 60 ))
if [ "$idle" -ge "$IDLE_MINUTES" ]; then
  stop_vm "Idle for $idle minutes"
fi
