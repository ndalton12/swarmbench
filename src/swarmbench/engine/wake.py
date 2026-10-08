"""Wake on activity: an agent that ends a turn or session isn't finished.

Coding agents often stop as soon as they've written a conclusion, which would end a
run at its most interesting point. Instead, an agent that ends its session sleeps and
is woken only by genuine new activity it hasn't seen: a direct message to it, a board
post in a channel it can read, or a file changed in its workspace by someone else
(including files the encounter sync brings in from another team). On waking it
continues its own conversation with a short note about what's new.

The run ends at the time limit, when the run is stopped, or once every agent is asleep
with nothing left that could wake anyone: no encounter still to come, no undelivered
messages, and no background jobs the agents started (processes they own that could still
write files). Then it ends after a short grace period (``advanced.extra.quiet_grace``,
default 60 s). If agents left background jobs running, it keeps waiting, since their
output can wake someone, and ends ``advanced.extra.quiet_period`` (default 2 min) after
the last one exits. Why it ended is recorded (``WakeController.end_reason``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio
from inspect_ai.log import transcript

from .layout import WORKSPACE

if TYPE_CHECKING:
    from .orchestrator import AgentRuntime, Swarm, TeamRuntime

POLL_SECONDS = 2.0
PREVIEW = 160
DEFAULT_QUIET_PERIOD = 120
DRY_RUN_QUIET_PERIOD = 10
DEFAULT_QUIET_GRACE = 60
DRY_RUN_QUIET_GRACE = 5
CLI_PROGRAMS = {"claude", "codex", "codex-code-mode-host"}
"""The agents' own CLIs (ignored if one lingers): they can't act without a model turn."""

PYTHON = "/usr/local/bin/python3"
# Lists /workspace as {path: [uid, mtime]} (regular files, no symlinks followed).
_LIST = r"""
import json, os, stat, sys
root = sys.argv[1]
out = {}
for dirpath, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))]
    for name in files:
        p = os.path.join(dirpath, name)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            out[p] = [st.st_uid, round(st.st_mtime, 3)]
print(json.dumps(out))
"""


# Agent-owned processes that could still produce files or messages: real uid in the
# given set, not a zombie. Prints [[pid, uid, args], ...].
_JOBS = r"""
import json, os, sys
uids = set(json.loads(sys.argv[1]))
skip = set(json.loads(sys.argv[2]))
out = []
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        with open(f"/proc/{pid}/status") as f:
            status = dict(line.split(":", 1) for line in f if ":" in line)
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            args = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        continue
    uid = int(status.get("Uid", "-1").split()[0])
    if uid not in uids or status.get("State", "").strip().startswith("Z") or not args:
        continue
    if os.path.basename(args[0]) in skip:
        continue
    out.append([int(pid), uid, " ".join(args)[:200]])
print(json.dumps(out))
"""


@dataclass
class Change:
    mono: float
    sandbox: str
    paths: list[str]
    actor: str | None
    """The agent (or team) that made the change, or None if it can't be attributed."""
    synced: bool = False


@dataclass
class WakeController:
    swarm: Swarm
    quiet_period: float
    changes: list[Change] = field(default_factory=list)
    last_activity: float = field(default_factory=time.monotonic)
    file_state: dict[str, dict[str, list]] = field(default_factory=dict)
    """Per sandbox: last seen {path: [uid, mtime]}."""
    quiet_grace: float = DEFAULT_QUIET_GRACE
    quiesced: bool = False
    end_reason: str | None = None
    """Why the run ended quietly, e.g. "all agents idle, no background jobs: ended after 60 s grace"."""
    last_job: str | None = None
    """The most recent background job still running when everyone was asleep."""
    last_job_seen: float | None = None

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def _relevant(self, sandbox: str, actor: str | None) -> bool:
        """Could this activity wake anyone? (A sleeping agent touching only its own files
        mustn't keep the run alive forever.)"""
        return any(
            a.info.sandbox == sandbox and a.info.name != actor and not a.done
            for a in self.swarm.agents.values()
        )

    def note_sync(self, sandbox: str, paths: list[str], author: str | None) -> None:
        """Files the encounter sync brought into a container from another team."""
        if paths:
            self.changes.append(Change(time.monotonic(), sandbox, list(paths), author, synced=True))
            if self._relevant(sandbox, author):
                self.touch()

    async def file_poll_loop(self, rt: TeamRuntime) -> None:
        assert rt.sandbox is not None
        uid_to_agent = {a.uid: a.name for a in rt.agents}
        while True:
            try:
                result = await rt.sandbox.exec(
                    [PYTHON, "-I", "-c", _LIST, WORKSPACE], user="root", timeout=60
                )
                if result.success:
                    import json

                    current = json.loads(result.stdout)
                    prev = self.file_state.get(rt.sandbox_name)
                    if prev is not None:
                        self._diff(rt.sandbox_name, prev, current, uid_to_agent)
                    self.file_state[rt.sandbox_name] = current
            except Exception:  # a failed poll must not end the run
                pass
            await anyio.sleep(POLL_SECONDS)

    def _diff(self, sandbox: str, prev: dict, current: dict, uid_to_agent: dict[int, str]) -> None:
        # group changed/new/deleted paths by the agent that owns them now (synced files are
        # attributed through note_sync, so root-owned changes we can't attribute are ignored
        # to avoid waking an agent on its own edit of a group-shared file)
        by_actor: dict[str, list[str]] = {}
        for path, meta in current.items():
            if prev.get(path) != meta:
                actor = uid_to_agent.get(meta[0])
                if actor is not None:
                    by_actor.setdefault(actor, []).append(path)
        for path in prev:
            if path not in current:
                actor = uid_to_agent.get(prev[path][0])
                if actor is not None:
                    by_actor.setdefault(actor, []).append(path)
        for actor, paths in by_actor.items():
            self.changes.append(Change(time.monotonic(), sandbox, sorted(paths), actor))
            if self._relevant(sandbox, actor):
                self.touch()

    def _triggers(self, art: AgentRuntime) -> tuple[list, list[Change]]:
        name = art.info.name
        msgs = [
            m
            for m in self.swarm.log.messages
            if m.id > art.wake_cursor
            and name in m.delivered_to
            and m.sender != name
            and name not in m.read_by
        ]
        files = [
            c for c in self.changes[art.file_cursor :] if c.sandbox == art.info.sandbox and c.actor != name
        ]
        return msgs, files

    async def wait_for_wake(self, art: AgentRuntime) -> str | None:
        """Sleep until there is new activity for this agent, and return a note about it.

        Returns None when the run should end instead (stopped, or everyone quiet).
        """
        art.sleep_start = time.monotonic()
        # record any board reads it just made, so posts it has seen don't wake it again
        await self.swarm.scan_boards()
        transcript().info(
            {"agent": art.info.name, "reason": "ended its turn; waiting for new activity"},
            source="swarm.agent_sleep",
        )
        while True:
            if self.swarm.stopping:
                return None
            msgs, files = self._triggers(art)  # checked before quiesce, so nothing pending is lost
            if msgs or files:
                note = self._format(art, msgs, files)
                art.wake_cursor = max([art.wake_cursor, *(m.id for m in msgs)])
                art.file_cursor = len(self.changes)
                self.swarm.log.mark_read(art.info.name, [m.id for m in msgs])
                art.sleep_start = time.monotonic()
                self.touch()
                transcript().info(
                    {
                        "agent": art.info.name,
                        "message_ids": [m.id for m in msgs],
                        "files": sorted({p for c in files for p in c.paths}),
                    },
                    source="swarm.agent_wake",
                )
                return note
            if self.quiesced:
                return None
            await anyio.sleep(POLL_SECONDS)

    def _format(self, art: AgentRuntime, msgs: list, files: list[Change]) -> str:
        bus = art.team.bus
        lines = ["[activity on this host]"]
        for m in msgs:
            who = bus.user_of(m.sender)
            preview = m.text.strip().replace("\n", " ")[:PREVIEW]
            if m.channel == "board":
                lines.append(f"{who} posted in #{m.board_channel}: {preview}")
            else:
                lines.append(f"{who} messaged you: {preview}")
        for c in files:
            paths = ", ".join(c.paths[:8]) + (" ..." if len(c.paths) > 8 else "")
            if c.synced:
                lines.append(f"new files appeared under the shared cache: {paths}")
            else:
                who = bus.user_of(c.actor) if c.actor else "someone"
                lines.append(f"{who} changed files in /workspace: {paths}")
        return "\n".join(lines)

    async def background_jobs(self) -> list[tuple[str, int, int, str]]:
        """Agent-owned processes in every team container: (team, pid, uid, command)."""
        import json

        jobs = []
        for rt in self.swarm.teams:
            if rt.sandbox is None:
                continue
            uids = [a.uid for a in rt.agents]
            try:
                result = await rt.sandbox.exec(
                    [PYTHON, "-I", "-c", _JOBS, json.dumps(uids), json.dumps(sorted(CLI_PROGRAMS))],
                    user="root",
                    timeout=60,
                )
            except Exception:  # can't tell: assume nothing is running
                continue
            if result.success:
                for pid, uid, cmd in json.loads(result.stdout or "[]"):
                    jobs.append((rt.team.name, pid, uid, cmd))
        return jobs

    async def quiesce_loop(self, agents: dict[str, AgentRuntime]) -> None:
        """End the run once nothing left could wake anyone (see the module docstring)."""
        while True:
            await anyio.sleep(min(POLL_SECONDS, self.quiet_grace / 2))
            if self.swarm.stopping:
                return
            alive = [a for a in agents.values() if not a.done]
            if not alive:
                return  # every agent has stopped for good (budget, crash): the run ends itself
            if any(a.running for a in alive):
                self.touch()
                self.last_job_seen = None  # a fresh all-asleep stretch starts from scratch
                continue
            # all alive agents are asleep: any pending trigger still counts as activity
            if any(self._triggers(a)[0] or self._triggers(a)[1] for a in alive if a.sleeping):
                self.touch()
                continue
            # never end quietly while an encounter is still to come: its announcement and
            # synced files will wake the sleepers (the clock restarts when it opens)
            if self.swarm.scenario.encounter is not None and not self.swarm.encounter_open:
                self.touch()
                continue
            jobs = await self.background_jobs()
            if jobs:
                team, pid, uid, cmd = jobs[0]
                user = next((a.info.user for a in agents.values() if a.info.uid == uid), str(uid))
                self.last_job = f"{user}'s background job (pid {pid}: {cmd[:80]})"
                self.last_job_seen = time.monotonic()
                continue
            # nothing could wake anyone: a short grace, or the quiet period after the last job
            if self.last_job_seen is not None:
                idle_since, wait = max(self.last_activity, self.last_job_seen), self.quiet_period
                reason = f"waited for {self.last_job} to finish; ended {wait:.0f} s after the last one exited"
            else:
                idle_since, wait = self.last_activity, self.quiet_grace
                reason = f"all agents idle, no background jobs: ended after {wait:.0f} s grace"
            if time.monotonic() - idle_since >= wait:
                before = self.last_activity
                await self.swarm.scan_boards()
                await anyio.sleep(POLL_SECONDS * 1.5)  # a file poll and sync pass complete meanwhile
                if self.last_activity != before or any(
                    self._triggers(a)[0] or self._triggers(a)[1] for a in alive if a.sleeping
                ):
                    continue
                self.end_reason = reason
                transcript().info({"reason": reason}, source="swarm.run_end")
                self.quiesced = True
                return


def quiet_period_for(swarm: Swarm) -> float:
    return _extra_seconds(swarm, "quiet_period", DEFAULT_QUIET_PERIOD, DRY_RUN_QUIET_PERIOD)


def quiet_grace_for(swarm: Swarm) -> float:
    return _extra_seconds(swarm, "quiet_grace", DEFAULT_QUIET_GRACE, DRY_RUN_QUIET_GRACE)


def _extra_seconds(swarm: Swarm, key: str, default: float, dry_default: float) -> float:
    extra = swarm.scenario.advanced.extra
    if key in extra:
        from swarmbench.config import parse_duration

        return float(parse_duration(extra[key]))
    return dry_default if swarm.dry_model is not None else default
