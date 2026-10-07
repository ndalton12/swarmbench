"""Preparing a team container at the start of a sample.

The writable areas are empty tmpfs mounts when the container starts. This fills
them from the pristine copies baked into the team image (root-only), sets up each
agent's home as that agent, and checks that the network is unreachable.
"""

from __future__ import annotations

import shlex

from inspect_ai.util import SandboxEnvironment

from swarmbench.types import AgentInfo

from .layout import BOARD, SEED_DIR, WORKSPACE

SH = "/bin/sh"


class SetupError(RuntimeError):
    pass


async def _run(sandbox: SandboxEnvironment, script: str, user: str, what: str) -> str:
    result = await sandbox.exec([SH, "-c", script], user=user, timeout=300)
    if not result.success:
        raise SetupError(f"{what} failed (exit {result.returncode}): {result.stderr.strip()[-2000:]}")
    return result.stdout


SEED_WORKSPACE = f"""
set -e
cp -a --no-preserve=ownership {SEED_DIR}/workspace/. {WORKSPACE}/
chmod -R g+rwX {WORKSPACE}
find {WORKSPACE} -type d -exec chmod g+s {{}} +
chmod 2775 {WORKSPACE}
# Agents run with umask 077; default ACLs keep the shared areas group-shared anyway.
setfacl -R -m g::rwX {WORKSPACE}
find {WORKSPACE} -type d -exec setfacl -d -m u::rwx,g::rwx,o::rx {{}} +
"""

# Seeded posts live under <seed>/board/<author>/<channel>/. Root creates the channels
# and lists the authors; each author then copies their own posts, so they own them.
SEED_BOARD_ROOT = f"""
set -e
for d in {SEED_DIR}/board/*/*/; do
  [ -d "$d" ] || continue
  c=$(basename "$d")
  mkdir -p {BOARD}/$c && chmod 3775 {BOARD}/$c
done
find {BOARD} -type d -exec setfacl -d -m u::rwx,g::rx,o::rx {{}} +
for a in {SEED_DIR}/board/*/; do [ -d "$a" ] && basename "$a"; done
"""
SEED_BOARD_AUTHOR = f"""
set -e
cd {SEED_DIR}/board/"$(id -un)"
for f in */*; do
  [ -f "$f" ] || continue
  cp -p "$f" {BOARD}/"$f"
  chmod 644 {BOARD}/"$f"
done
"""

HOME_SETUP = """
set -e
cd "$HOME"
cp -r /etc/skel/. "$HOME"/
mkdir -p "$HOME/.local/bin"
# CLI session and config state is private to its agent (root writes Codex's config via group)
mkdir -p -m 700 "$HOME/.claude"
mkdir -p -m 2770 "$HOME/.codex"
chmod 700 "$HOME/.claude"
chmod 2770 "$HOME/.codex"
git config --global user.name {user}
git config --global user.email {user}@{host}
touch -d '-30 days' "$HOME/.bashrc" "$HOME/.profile" "$HOME/.gitconfig"
"""

NETWORK_CHECK = r"""
import socket, sys
problems = []
try:
    socket.getaddrinfo("pypi.org", 443)
    problems.append("DNS lookup succeeded")
except OSError:
    pass
for host in ("1.1.1.1", "8.8.8.8"):
    try:
        socket.create_connection((host, 443), timeout=3).close()
        problems.append(f"connected to {host}")
    except OSError:
        pass
ifaces = [name for _, name in socket.if_nameindex() if name != "lo"]
if ifaces:
    problems.append(f"network interfaces present: {ifaces}")
print("; ".join(problems))
sys.exit(1 if problems else 0)
"""


async def prepare_container(
    sandbox: SandboxEnvironment,
    agents: list[AgentInfo],
    hostname: str,
    board_enabled: bool,
) -> None:
    await _run(sandbox, SEED_WORKSPACE, "root", "seeding /workspace")
    authors = (await _run(sandbox, SEED_BOARD_ROOT, "root", "creating board channels")).split()
    for author in authors:
        await _run(sandbox, SEED_BOARD_AUTHOR, author, f"seeding board posts by {author}")
    if not board_enabled:
        # messaging without the board: the board folder stays, but nobody can use it
        await _run(sandbox, f"chmod 0700 {BOARD}", "root", "closing the board")
    for agent in agents:
        script = HOME_SETUP.format(user=shlex.quote(agent.user), host=shlex.quote(hostname))
        await _run(sandbox, script, agent.user, f"setting up {agent.home}")
    await check_network(sandbox, agents[0].user if agents else "nobody")


async def check_network(sandbox: SandboxEnvironment, user: str) -> None:
    result = await sandbox.exec(["/usr/local/bin/python3", "-I", "-c", NETWORK_CHECK], user=user, timeout=60)
    if not result.success:
        raise SetupError(f"container network is reachable: {result.stdout.strip() or result.stderr.strip()}")
