#!/usr/bin/env bash
# Copy your Claude Code settings from this Mac to a remote machine (e.g. a swarmbench VM).
# Run it on the Mac:
#
#   deploy/copy-claude-settings.sh ubuntu@1.2.3.4 [-i ~/.ssh/key.pem] [--repo-path /home/ubuntu/swarmbench]
#   deploy/copy-claude-settings.sh --dry-run /tmp/preview      # build the copy locally and show it
#
# What is copied (from ~/.claude):
#   CLAUDE.md, statusline.sh, settings.json (known keys only: permissions, hooks, plugins, model and
#   display settings; never "env"), hooks/, skills/, mods/, plugins/ (without plugin data), and this
#   project's memory folder, renamed for the project's path on the remote machine.
# Files that look like credentials (.env, *.pem, *token*, *secret*, *auth*.json, ...) are skipped,
# and the copy is refused if anything left still looks like a key.
# Paths under your home folder are rewritten to the remote home folder.
# Never copied: login credentials, chat history, session transcripts, job folders, the daemon state.
# Existing remote files with the same names are overwritten; other remote files are left alone.
set -euo pipefail

TARGET=""
KEY=""
REMOTE_REPO=""
PREVIEW=""
while [ $# -gt 0 ]; do
  case "$1" in
    -i) KEY="$2"; shift 2 ;;
    --repo-path) REMOTE_REPO="$2"; shift 2 ;;
    --dry-run) PREVIEW="$2"; shift 2 ;;
    -h|--help) sed -n 2,14p "$0"; exit 0 ;;
    *) TARGET="$1"; shift ;;
  esac
done
[ -n "$TARGET" ] || [ -n "$PREVIEW" ] || { echo "usage: $0 user@host [-i key] [--repo-path PATH] | --dry-run DIR" >&2; exit 2; }

SRC="$HOME/.claude"
LOCAL_REPO="$(cd "$(dirname "$0")/.." && pwd)"
SSH=(ssh -o StrictHostKeyChecking=accept-new)
[ -n "$KEY" ] && SSH+=(-i "$KEY")

if [ -n "$PREVIEW" ]; then
  REMOTE_HOME="/home/ubuntu"
else
  REMOTE_HOME="$("${SSH[@]}" "$TARGET" 'printf %s "$HOME"')"
fi
REMOTE_REPO="${REMOTE_REPO:-$REMOTE_HOME/swarmbench}"
# Claude Code names a project's folder after its path, with every character other than a letter
# or digit replaced by - (e.g. /Users/niall/code/mats_swarm -> -Users-niall-code-mats-swarm).
project_key() { printf '%s' "$1" | sed 's#[^A-Za-z0-9]#-#g'; }
LOCAL_KEY="$(project_key "$LOCAL_REPO")"
REMOTE_KEY="$(project_key "$REMOTE_REPO")"

STAGE="$(mktemp -d)"
trap 'rm -r "$STAGE"' EXIT
OUT="$STAGE/.claude"
mkdir -p "$OUT"

# Never copy anything that looks like a credential, wherever it sits.
SECRET_EXCLUDES=(--exclude '.DS_Store' --exclude '.trash/' --exclude 'data/' --exclude '*.tmp'
  --exclude '.env' --exclude '.env.*' --exclude '*.pem' --exclude '*.key' --exclude '*.p12'
  --exclude '*credential*' --exclude '*secret*' --exclude '*token*' --exclude '*auth*.json'
  --exclude '.netrc' --exclude 'node_modules/')

for f in CLAUDE.md statusline.sh; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$OUT/"
done
for d in hooks skills mods plugins; do
  [ -d "$SRC/$d" ] && rsync -a "${SECRET_EXCLUDES[@]}" "$SRC/$d/" "$OUT/$d/"
done
if [ -d "$SRC/projects/$LOCAL_KEY/memory" ]; then
  mkdir -p "$OUT/projects/$REMOTE_KEY"
  rsync -a "$SRC/projects/$LOCAL_KEY/memory/" "$OUT/projects/$REMOTE_KEY/memory/"
fi
# settings.json: only these keys. Others (e.g. "env", "apiKeyHelper") can hold secrets.
if [ -f "$SRC/settings.json" ]; then
  python3 - "$SRC/settings.json" "$OUT/settings.json" <<'PY'
import json, sys
keep = {"permissions", "hooks", "statusLine", "enabledPlugins", "extraKnownMarketplaces",
        "effortLevel", "modelSettings", "theme", "model", "outputStyle", "includeCoAuthoredBy"}
d = json.load(open(sys.argv[1]))
dropped = sorted(k for k in d if k not in keep)
json.dump({k: v for k, v in d.items() if k in keep}, open(sys.argv[2], "w"), indent=2)
if dropped:
    print("note: left out these settings.json keys: " + ", ".join(dropped))
PY
fi

# Rewrite this Mac's paths (home folder, then the repo) in text files.
python3 - "$OUT" "$HOME" "$REMOTE_HOME" "$LOCAL_REPO" "$REMOTE_REPO" <<'PY'
import json, os, sys
out, home, rhome, repo, rrepo = sys.argv[1:]
text_ext = {".json", ".md", ".sh", ".py", ".txt", ".yaml", ".yml", ".toml"}
changed = 0
for root, _, files in os.walk(out):
    for name in files:
        path = os.path.join(root, name)
        if os.path.splitext(name)[1] not in text_ext:
            continue
        try:
            s = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        t = s.replace(repo, rrepo).replace(home, rhome)
        if t != s:
            open(path, "w", encoding="utf-8").write(t)
            changed += 1
# A status line command that doesn't exist here won't exist there either.
settings = os.path.join(out, "settings.json")
if os.path.exists(settings):
    d = json.load(open(settings))
    cmd = (d.get("statusLine") or {}).get("command", "")
    if cmd and not os.path.exists(os.path.expanduser(cmd.split()[0].replace(rhome, home))):
        d.pop("statusLine")
        json.dump(d, open(settings, "w"), indent=2)
        print("note: dropped the statusLine setting (its command isn't on this Mac)")
print(f"rewrote paths in {changed} file(s)")
PY

# Last check: refuse to send anything that looks like a real key.
if hits="$(grep -rlE 'sk-ant-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{40,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----' "$OUT")"; then
  echo "Refusing to copy: these files look like they contain a key or token:" >&2
  printf '  %s\n' $hits | sed "s#$OUT/##" >&2
  exit 1
fi

echo "Prepared (from $SRC):"
(cd "$OUT" && find . -maxdepth 2 -mindepth 1 | sort | sed 's#^\./#  #')
echo "Project memory: projects/$LOCAL_KEY/memory -> projects/$REMOTE_KEY/memory"

if [ -n "$PREVIEW" ]; then
  mkdir -p "$PREVIEW"
  rsync -a "$OUT/" "$PREVIEW/.claude/"
  echo "Dry run: wrote the copy to $PREVIEW/.claude (nothing was sent)."
  exit 0
fi

RSH="ssh -o StrictHostKeyChecking=accept-new${KEY:+ -i $KEY}"
rsync -a -e "$RSH" "$OUT/" "$TARGET:.claude/"
"${SSH[@]}" "$TARGET" 'chmod 700 ~/.claude'
echo "Copied to $TARGET:~/.claude"
echo "Log in to Claude Code on the remote machine yourself (credentials are never copied)."
echo "Note: notification hooks that use macOS tools do nothing on Linux; they fail quietly."
