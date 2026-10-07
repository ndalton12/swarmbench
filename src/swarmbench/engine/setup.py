"""Preparing a team container at the start of a sample.

The writable areas are empty tmpfs mounts when the container starts. This fills
them from the pristine copies baked into the team image (root-only), sets up each
agent's home as that agent, and checks that the network is unreachable.
"""

from __future__ import annotations

import json
import shlex

from inspect_ai.util import SandboxEnvironment

from swarmbench.types import AgentInfo

from .layout import (
    BOARD,
    RELAY_DIR,
    RELAY_LOG,
    RELAY_PATH,
    SEED_DIR,
    WORKSPACE,
    front_port,
)

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
    await start_gateway(sandbox, agents)
    await check_network(sandbox, agents[0].user if agents else "nobody")


async def start_gateway(sandbox: SandboxEnvironment, agents: list[AgentInfo]) -> None:
    """Start the request gateway and route agents' bridge traffic through it.

    Each inspect-swe agent has a bridge port. A firewall rule redirects any non-root
    connection to that port to the gateway's front port; the gateway reads the real uid
    and forwards to the bridge. Root (the framework's own proxy) is excluded, so it
    reaches the bridge directly. This is the only way a non-root process reaches a bridge.
    """
    ports = {front_port(a.bridge_port): a.bridge_port for a in agents if a.bridge_port is not None}
    if not ports:
        return
    config = {"ports": {str(f): r for f, r in ports.items()}, "log": RELAY_LOG}
    await sandbox.exec(
        [SH, "-c", f"mkdir -p {RELAY_DIR} && chmod 700 {RELAY_DIR} && cat > {RELAY_DIR}/config.json"],
        input=json.dumps(config),
        user="root",
        timeout=60,
    )
    # Start the gateway first and wait until every listener is up, then install the rules,
    # so there is never a moment when a redirect points at nothing.
    await _run(
        sandbox,
        f"rm -f {RELAY_DIR}/ready\n"
        f"nohup /usr/local/bin/python3 -I {RELAY_PATH} {RELAY_DIR}/config.json "
        f">{RELAY_DIR}/svcgwd.log 2>&1 &\n"
        f"for i in $(seq 100); do [ -e {RELAY_DIR}/ready ] && exit 0; sleep 0.1; done\n"
        f"echo 'gateway did not start' >&2; cat {RELAY_DIR}/svcgwd.log >&2; exit 1",
        "root",
        "starting the gateway",
    )
    v4 = ["set -e"] + [
        f"iptables -t nat -A OUTPUT -o lo -p tcp --dport {real} -m owner ! --uid-owner 0 "
        f"-j REDIRECT --to-ports {f}"
        for f, real in ports.items()
    ]
    await _run(sandbox, "\n".join(v4), "root", "installing gateway firewall rules")
    # The gateway listens on IPv4 only, so non-root IPv6 connections to a bridge port are
    # refused outright. If IPv6 loopback exists and the rule can't be installed, fail closed.
    v6 = ["set -e", "[ -s /proc/net/if_inet6 ] || exit 0"] + [
        f"ip6tables -A OUTPUT -o lo -p tcp --dport {real} -m owner ! --uid-owner 0 -j REJECT"
        for real in ports.values()
    ]
    await _run(sandbox, "\n".join(v6), "root", "blocking IPv6 access to the bridges")
    check = await sandbox.exec(["/usr/sbin/iptables", "-t", "nat", "-S", "OUTPUT"], user="root", timeout=60)
    missing = [real for real in ports.values() if f"--dport {real} " not in check.stdout]
    if not check.success or missing:
        raise SetupError(f"gateway firewall rules missing for bridge ports {missing}: {check.stderr.strip()}")


async def check_network(sandbox: SandboxEnvironment, user: str) -> None:
    result = await sandbox.exec(["/usr/local/bin/python3", "-I", "-c", NETWORK_CHECK], user=user, timeout=60)
    if not result.success:
        raise SetupError(f"container network is reachable: {result.stdout.strip() or result.stderr.strip()}")
