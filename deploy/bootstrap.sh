#!/usr/bin/env bash
# Set up a fresh Ubuntu 24.04 machine (ARM or x86) to run swarmbench. Run it ON the VM, from
# the copied repo:  bash deploy/bootstrap.sh [--claude] [--no-checks]
#
#   --claude      also install Claude Code (and Node.js + the Codex CLI, used for Codex reviews)
#   --no-checks   skip the Docker tests and the dry run at the end
#
# Safe to re-run. Needs sudo. Makes no model API calls (the dry run uses the mock model).
set -euo pipefail

WITH_CLAUDE=0
CHECKS=1
for arg in "$@"; do
  case "$arg" in
    --claude) WITH_CLAUDE=1 ;;
    --no-checks) CHECKS=0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
say() { printf '\n==> %s\n' "$*"; }

say "System packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  ca-certificates curl git tmux rsync python3 jq >/dev/null

if ! command -v docker >/dev/null 2>&1; then
  say "Docker Engine (with the compose plugin)"
  curl -fsSL https://get.docker.com | sudo sh >/dev/null
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker >/dev/null 2>&1 || true

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  say "uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
export PATH="$HOME/.local/bin:$PATH"
grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >>"$HOME/.bashrc"

if [ "$WITH_CLAUDE" = 1 ]; then
  if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
    say "Claude Code"
    curl -fsSL https://claude.ai/install.sh | bash
  fi
  if ! command -v codex >/dev/null 2>&1; then
    say "Node.js and the Codex CLI"
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - >/dev/null
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
    sudo npm install -g @openai/codex >/dev/null
  fi
fi

say "Python environment"
cd "$REPO"
uv sync

# A new docker group membership only applies to new logins, so run Docker steps through sg.
in_docker_group() { sg docker -c "cd '$REPO' && export PATH='$PATH' && $*"; }

if [ "$CHECKS" = 1 ]; then
  say "Docker tests, one file at a time (the first one builds the container image)"
  for f in tests/test_docker.py tests/test_watcher_docker.py tests/test_watch_docker.py; do
    [ -f "$f" ] && in_docker_group "uv run pytest -q $f"
  done
  say "Dry run (mock model, no API calls)"
  in_docker_group "uv run swarm run scenarios/impossible_math --dry-run --attached"
fi

say "Done"
echo "Resources: $(nproc) CPUs, $(free -g | awk '/Mem:/{print $2}') GB memory."
echo "Log out and back in once so that 'docker' works without sudo."
[ -f "$REPO/.env" ] || echo "No .env yet: copy your API keys to $REPO/.env before real runs."
if [ "$WITH_CLAUDE" = 1 ]; then
  cat <<EOF

To run Claude Code here with Remote Control:
  tmux new -s claude            # keeps it running after you disconnect (detach: Ctrl-b d)
  cd $REPO && claude            # first time: log in, then /exit
  codex login                   # optional, for Codex reviews
  claude --remote-control "swarmbench"
Then open the printed URL, scan its QR code, or pick the session at claude.ai/code.
EOF
fi
