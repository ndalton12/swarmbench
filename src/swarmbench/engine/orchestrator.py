"""The orchestrator: one Inspect solver that runs a whole swarm as one sample.

It prepares each team container, starts every agent at once (each in its own
``agent`` span, as its own Linux user), runs the board scanner, the stop check,
live status and any encounter in the background, and at the end writes the
message history, per-agent usage and problems to the sample store.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio
from inspect_ai.agent import AgentState, run
from inspect_ai.log import transcript
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, Model, ModelUsage
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import LimitExceededError, SandboxEnvironment, sandbox, store, token_limit

from swarmbench.config import ResolvedTeam, Scenario
from swarmbench.paths import RunDir
from swarmbench.types import AgentInfo, CostSummary

from .board import BoardScanner
from .bridgefilter import BridgeFilter, usage_of
from .context import set_current_agent
from .costguard import CostLedger
from .dryrun import set_dry_run
from .gatewaylog import MAX_STORE_RECORDS, GatewayCollector
from .harness import build_agent, react_system
from .layout import OPS_UID, OPS_USER, agent_infos, team_hostname, team_sandbox
from .messages import MessageBus, SwarmLog
from .mock import MockSwarmModel, default_script
from .ports import PortAllocator
from .setup import prepare_container
from .snapshot import diff, snapshot
from .text import render_dates, render_prompt
from .wake import WakeController, quiet_grace_for, quiet_period_for

BOARD_SCAN_SECONDS = 2.0
STOP_POLL_SECONDS = 1.0
STATUS_SECONDS = 3.0
STOP_GRACE_SECONDS = 20.0
BUDGET_GRACE_SECONDS = 30.0
STOP_FILE = "stop_requested"
LEASE_FILE = "/var/backups/.lease"
"""Renewed every LEASE_RENEW_SECONDS; PID 1 stops the container if it lapses (see docker/init.c)."""
LEASE_RENEW_SECONDS = 30.0
GATEWAY_DRAIN_SECONDS = 5.0
"""A file in the run folder: if it exists, the run stops gracefully (its text is the reason)."""


def add_problem(text: str) -> None:
    problems = list(store().get("swarm_problems", []))
    problems.append(text)
    store().set("swarm_problems", problems)


# Hooks the runner and tests can set for a run (keyed by run id), since the solver
# runs inside inspect_ai.eval() in the same process.
@dataclass
class RunHooks:
    status: Any | None = None
    """A StatusWriter, updated every few seconds."""
    mock: MockSwarmModel | None = None
    scripts: dict[str, list[Any]] = field(default_factory=dict)
    """Mock scripts by agent name (dry runs and tests)."""
    on_start: Callable[[Swarm], Any] | None = None
    """Called (and awaited if async) once all agents have been started."""
    finished_costs: list[CostSummary] = field(default_factory=list)
    """Cost of each epoch already finished in this run (status shows the running total)."""


HOOKS: dict[str, RunHooks] = {}


@dataclass
class TeamRuntime:
    team: ResolvedTeam
    index: int
    sandbox_name: str
    hostname: str
    agents: list[AgentInfo]
    bus: MessageBus
    board: bool
    direct: bool
    notice_direct: bool
    notice_board: bool
    sandbox: SandboxEnvironment | None = None
    scanner: BoardScanner | None = None

    @property
    def wants_notice(self) -> bool:
        """Whether new messages are pushed to agents as a digest (direct and/or board)."""
        return (self.direct and self.notice_direct) or (self.board and self.notice_board)

    start_snapshot: dict[str, Any] | None = None


@dataclass
class AgentRuntime:
    info: AgentInfo
    team: TeamRuntime
    prompt: str
    meter: Any = None
    filter: BridgeFilter | None = None
    scope: anyio.CancelScope | None = None
    running: bool = False
    sleeping: bool = False
    done: bool = False
    stop_reason: str | None = None
    sleep_start: float = 0.0
    wake_cursor: int = 0
    """Highest message id delivered to the agent by a wake note."""
    file_cursor: int = 0
    """How many workspace changes had been reported to the agent by a wake note."""


class Swarm:
    def __init__(
        self,
        scenario: Scenario,
        run_dir: RunDir | None,
        run_id: str,
        dry_model: Model | None,
        run_start: datetime | None = None,
    ) -> None:
        self.scenario = scenario
        self.run_start = run_start or datetime.now().astimezone()
        self.run_dir = run_dir
        self.run_id = run_id
        self.dry_model = dry_model
        self.hooks = HOOKS.get(run_id, RunHooks())
        self.log = SwarmLog()
        self.allocator = PortAllocator()
        self.stop_reason: str | None = None
        self.started = time.monotonic()
        self.teams: list[TeamRuntime] = []
        self.agents: dict[str, AgentRuntime] = {}
        self.default_sandbox = team_sandbox(scenario.resolved_teams()[0])
        self.background: anyio.abc.TaskGroup | None = None
        self.compose_project: str | None = None
        self.encounter_open = False
        self._scan_lock: anyio.Lock | None = None
        self.gateway: dict[str, GatewayCollector] = {}
        self.gateway_down: set[str] = set()
        self.stop_source: str | None = None
        """"monitor" or "user", once a stop was requested."""
        self.sample_error: str | None = None
        self.wake = WakeController(self, quiet_period_for(self), quiet_grace=quiet_grace_for(self))
        self.ledger = CostLedger(scenario.max_cost, on_cap=self._cost_cap_reached)
        self.log.listeners.append(lambda m: self.wake.touch())

        infos = agent_infos(scenario)
        if dry_model is not None:
            for info in infos:
                info.model = str(dry_model)
        for index, team in enumerate(scenario.resolved_teams()):
            members = [a for a in infos if a.team == team.name]
            delivery = team.delivery
            rt = TeamRuntime(
                team=team,
                index=index,
                sandbox_name=team_sandbox(team),
                hostname=team_hostname(scenario, index),
                agents=members,
                bus=MessageBus(self.log, members),
                board=team.messaging in ("board", "both"),
                direct=team.messaging in ("direct", "both"),
                notice_direct=(delivery or "notice") == "notice",
                notice_board=delivery == "notice",
            )
            self.teams.append(rt)
            template = scenario.path(team.prompt).read_text() if scenario.root else team.prompt
            template = render_dates(template, self.run_start)
            users = [a.user for a in members]
            for info in members:
                prompt = render_prompt(template, info.user, rt.hostname, users)
                self.agents[info.name] = AgentRuntime(info=info, team=rt, prompt=prompt)
                if info.harness != "react":
                    # known before anything starts, so the monitor can watch these ports
                    info.bridge_port = self.allocator.reserve(info.sandbox)

    # ------------------------------------------------------------------ run

    @property
    def stopping(self) -> bool:
        return self.stop_reason is not None

    def infos(self) -> list[AgentInfo]:
        return [a.info for a in self.agents.values()]

    async def run(self, state: TaskState) -> None:
        store().set("swarm_problems", list(store().get("swarm_problems", [])))
        for rt in self.teams:
            rt.sandbox = sandbox(rt.sandbox_name)
        self.compose_project = compose_project_of(self.teams[0].sandbox)
        self._update_status(force=True)
        async with anyio.create_task_group() as tg:
            for rt in self.teams:
                tg.start_soon(self._prepare_team, rt)

        if self.dry_model is not None:
            self._install_mock_scripts()

        sandboxes = {rt.sandbox_name: rt.sandbox for rt in self.teams if rt.sandbox is not None}
        self.started = time.monotonic()  # encounter times count from when the agents start
        try:
            async with monitor_watch(self.scenario, self.run_dir, self.infos(), sandboxes):
                async with anyio.create_task_group() as background:
                    self.background = background
                    background.start_soon(self._board_loop)
                    background.start_soon(self._stop_loop)
                    background.start_soon(self._status_loop)
                    background.start_soon(self._lease_loop)
                    background.start_soon(self._gateway_loop)
                    background.start_soon(self.wake.quiesce_loop, self.agents)
                    for rt in self.teams:
                        background.start_soon(self.wake.file_poll_loop, rt)
                    if self.scenario.encounter is not None:
                        from .encounter import run_encounter

                        background.start_soon(run_encounter, self)
                    try:
                        await self._run_agents(background)
                    finally:
                        background.cancel_scope.cancel()
        except BaseException as ex:
            if not isinstance(ex, anyio.get_cancelled_exc_class()):
                self.sample_error = f"{type(ex).__name__}: {str(ex)[:500]}"
            else:
                self.sample_error = "cancelled"
            raise
        finally:
            with anyio.CancelScope(shield=True):
                await self._final_scan()
                await self._end_snapshots()
                await self._read_relay_logs()
                self._write_store(state)
                self._update_status(force=True)
                self.hooks.finished_costs.append(self.cost_summary())

    async def _gateway_loop(self) -> None:
        while True:
            await anyio.sleep(GATEWAY_DRAIN_SECONDS)
            for team, collector in self.gateway.items():
                await collector.drain()
                if not await collector.check_alive() and team not in self.gateway_down:
                    self._gateway_died(team)

    def _gateway_died(self, team: str) -> None:
        """The request gateway stopped: attribution evidence is lost from now on, and the team's
        Claude Code / Codex agents can no longer reach their models (the firewall keeps sending
        them to the gateway, which fails closed)."""
        self.gateway_down.add(team)
        add_problem(
            f"request gateway for team {team} stopped: attribution evidence lost from then on, and "
            "that team's Claude Code/Codex agents lost model access"
        )
        transcript().info(
            {"team": team, "reason": "gateway process not running"}, source="swarm.gateway_down"
        )

    async def _read_relay_logs(self) -> None:
        """Collect the rest of the gateway's records and put them (and the exact join) in the store."""
        records: list[dict[str, Any]] = []
        for team, collector in self.gateway.items():
            for _ in range(200):  # bounded: at most ~800 MB of records
                if not await collector.drain():
                    break
            if not await collector.check_alive() and team not in self.gateway_down:
                self._gateway_died(team)
            if collector.errors:
                add_problem(
                    f"gateway evidence gap for team {team}: {len(collector.errors)} collection "
                    f"problem(s), e.g. {collector.errors[0]}"
                )
            records.extend(collector.records)
        if len(records) > MAX_STORE_RECORDS:
            add_problem(
                f"gateway records truncated in the log: {len(records)} collected, first "
                f"{MAX_STORE_RECORDS} kept in the store; all are in the run folder under gateway/"
            )
        store().set("swarm_bridge_requests", records[:MAX_STORE_RECORDS])
        store().set("swarm_request_actors", self.join_request_actors(records))

    def join_request_actors(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Who really made each bridged model request: gateway evidence joined exactly.

        Each swarm.attribution event carries the canonical-JSON sha256 of the request body the
        bridge received; the gateway logs the same digest with the kernel-verified uid of the
        connection that carried it. A request whose matching gateway records all have one uid
        is "exact"; records with different uids are "ambiguous" (never guessed); no matching
        record is "none".
        """
        by_key: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
        for r in records:
            if r.get("t") == "request" and r.get("body_json_sha256"):
                by_key.setdefault((r["sandbox"], r["bridge_port"], r["body_json_sha256"]), []).append(r)
        out: dict[str, Any] = {}
        for art in self.agents.values():
            if art.filter is None or art.info.bridge_port is None:
                continue
            uid_to_agent = {a.uid: a.name for a in art.team.agents}
            for rec in art.filter.records:
                digest = rec.get("body_sha256")
                matches = by_key.get((art.info.sandbox, art.info.bridge_port, digest), []) if digest else []
                uids = sorted({m["uid"] for m in matches})
                match = "exact" if len(uids) == 1 else ("ambiguous" if uids else "none")
                uid = uids[0] if match == "exact" else None
                out[rec["request_id"]] = {
                    "bridge_of": art.info.name,
                    "match": match,
                    "actor_uid": uid,
                    "actor": uid_to_agent.get(uid) if uid is not None else None,
                    "candidate_uids": uids,
                    "gateway_seq": [m.get("seq") for m in matches],
                    "claimed_actor": rec.get("claimed_actor"),
                    "generated": rec.get("generated"),
                }
        return out

    async def _prepare_team(self, rt: TeamRuntime) -> None:
        assert rt.sandbox is not None
        await self.renew_leases()
        await prepare_container(rt.sandbox, rt.agents, rt.hostname, rt.board)
        known = {OPS_UID: OPS_USER}
        rt.scanner = BoardScanner(self.log, rt.sandbox, rt.agents, known)
        await rt.scanner.scan()  # baseline: posts that exist before anyone starts
        rt.start_snapshot = await self._snapshot(rt, "start")
        if any(a.bridge_port for a in rt.agents):
            out = self.run_dir.root / "gateway" / f"{rt.team.name}.jsonl" if self.run_dir else None
            self.gateway[rt.team.name] = GatewayCollector(rt.sandbox_name, rt.sandbox, out)

    async def _snapshot(self, rt: TeamRuntime, which: str) -> dict[str, Any] | None:
        """Save the team's /workspace to runs/<id>/workspace/<team>/<which>.tar.gz."""
        if self.run_dir is None or rt.sandbox is None:
            return None
        try:
            dest = self.run_dir.root / "workspace" / rt.team.name / f"{which}.tar.gz"
            return await snapshot(rt.sandbox, rt.agents, dest)
        except Exception as ex:  # evidence is lost, but the run itself is fine
            add_problem(f"workspace snapshot ({which}) failed for team {rt.team.name}: {str(ex)[:300]}")
            return None

    async def _end_snapshots(self) -> None:
        diffs: dict[str, Any] = {}
        for rt in self.teams:
            end = await self._snapshot(rt, "end")
            if rt.start_snapshot is not None and end is not None:
                d = diff(rt.start_snapshot, end, rt.agents)
                d["start_archive"] = f"workspace/{rt.team.name}/start.tar.gz"
                d["end_archive"] = f"workspace/{rt.team.name}/end.tar.gz"
                diffs[rt.team.name] = d
                if d["truncated"]:
                    add_problem(f"workspace diff for team {rt.team.name} is incomplete (size or count caps)")
        store().set("swarm_workspace_diff", diffs)

    def _install_mock_scripts(self) -> None:
        mock = self.hooks.mock
        if mock is None:
            return
        for name, art in self.agents.items():
            others = [a for a in art.team.agents if a.name != name]
            steps = self.hooks.scripts.get(name) or default_script(
                art.info, others, art.team.board, art.team.direct
            )
            mock.set_script(art.info, steps)

    async def _run_agents(self, background: anyio.abc.TaskGroup) -> None:
        async with anyio.create_task_group() as agents_tg:
            for art in self.agents.values():
                art.running = True
                agents_tg.start_soon(self._run_agent, art, background)
            if self.hooks.on_start is not None:
                result = self.hooks.on_start(self)
                if hasattr(result, "__await__"):
                    await result

    async def _run_agent(self, art: AgentRuntime, background: anyio.abc.TaskGroup) -> None:
        info = art.info
        set_current_agent(info.name)
        budget = art.team.team.per_agent_tokens
        is_react = info.harness == "react"
        # One meter per agent, entered for the whole lifetime, so usage accumulates across
        # resumed sessions. react sessions get a fresh per-session limit set to the remaining
        # budget; the CLI harnesses are held to budget by their bridge filter.
        art.meter = token_limit(None)
        if not is_react:
            art.filter = BridgeFilter(
                agent=info.name,
                user=info.user,
                peers={a.user: a.name for a in art.team.agents},
                budget=budget,
                meter=art.meter,
                bus=art.team.bus,
                notice=art.team.wants_notice,
                on_exhausted=lambda: background.start_soon(self._cancel_later, art, BUDGET_GRACE_SECONDS),
                should_stop=lambda: self.stopping,
                ledger=self.ledger,
            )
        agent = build_agent(
            info,
            art.team.team,
            hostname=art.team.hostname,
            bus=art.team.bus,
            direct=art.team.direct,
            notice=art.team.notice_direct and art.team.direct,
            should_stop=lambda: self.stopping,
            bridge_filter=art.filter,
            compaction=self.scenario.advanced.compaction,
            dry_model=self.dry_model,
            ledger=self.ledger,
        )
        # react keeps its own system message in the conversation (so a resumed session
        # doesn't gain a second one); the CLI harnesses carry it through system_prompt=.
        messages: list = []
        if is_react:
            messages.append(ChatMessageSystem(content=react_system(info, art.team.hostname)))
        messages.append(ChatMessageUser(content=art.prompt))

        reason = "finished"
        try:
            with art.meter:
                while True:
                    self.wake.touch()
                    session_reason, result = await self._run_session(art, agent, messages, is_react, budget)
                    if session_reason != "finished":
                        reason = session_reason
                        break
                    # the agent ended its session; sleep until there is new activity
                    art.running = False
                    art.sleeping = True
                    note = await self.wake.wait_for_wake(art)
                    art.sleeping = False
                    if note is None:
                        reason = "stopped" if self.stopping else "finished"
                        break
                    art.running = True
                    messages = [m for m in result.messages] + [ChatMessageUser(content=note)]
        except BaseException as ex:
            if not isinstance(ex, anyio.get_cancelled_exc_class()):
                raise
            if reason == "finished":
                reason = "stopped"
            raise
        finally:
            if self.stopping and reason == "finished":
                reason = "stopped"
            art.stop_reason = reason
            art.done = True
            art.running = False
            art.sleeping = False
            transcript().info({"agent": info.name, "reason": reason}, source="swarm.agent_stopped")

    async def _run_session(self, art, agent, messages, is_react, budget):  # type: ignore[no-untyped-def]
        """One session of an agent. Returns (reason, final AgentState)."""
        info = art.info
        result = None
        with anyio.CancelScope() as scope:
            art.scope = scope
            try:
                if is_react:
                    remaining = max(0, budget - int(usage_of(art.meter).total_tokens))
                    result, limit_error = await run(
                        agent, messages, limits=[token_limit(remaining)], name=info.name
                    )
                    if limit_error is not None:
                        return "budget", result
                else:
                    result = await self._run_on_own_port(art, agent, messages)
                    if art.filter is not None and art.filter.exhausted:
                        return "budget", result
            except LimitExceededError:
                raise  # sample-level limits (time, tokens, cost) end the whole run
            except Exception as ex:
                if is_terminate(ex):
                    raise
                add_problem(f"{info.name} crashed: {type(ex).__name__}: {str(ex)[:300]}")
                return f"crashed: {type(ex).__name__}: {str(ex)[:2000]}", result or _empty_state(messages)
        if scope.cancelled_caught:
            return art.stop_reason or "stopped", result or _empty_state(messages)
        return "finished", result or _empty_state(messages)

    async def _run_on_own_port(self, art: AgentRuntime, agent: Any, messages: list) -> Any:
        """Run one Claude Code / Codex session on the agent's own bridge port.

        inspect-swe picks a new port for every execution by bumping a counter in the sample
        store, so each session (including every resume after a wake) is pinned back to the
        agent's port, which the gateway and its firewall rule protect. The previous session's
        bridge has already shut down, so the port is free.
        """
        port = art.info.bridge_port
        assert port is not None
        box: dict[str, Any] = {}
        done = anyio.Event()

        async def session() -> None:
            try:
                box["result"] = await run(agent, messages, name=art.info.name)
            except BaseException as ex:  # re-raised below, in this agent's own task
                box["error"] = ex
                if isinstance(ex, anyio.get_cancelled_exc_class()):
                    raise
            finally:
                done.set()

        async with anyio.create_task_group() as tg:
            await self.allocator.start_with_port(
                port, art.info.harness, start=lambda: tg.start_soon(session), finished=done.is_set
            )
        if "error" in box:
            raise box["error"]
        return box.get("result")

    async def _cancel_later(self, art: AgentRuntime, delay: float) -> None:
        await anyio.sleep(delay)
        if not art.done and art.scope is not None:
            art.stop_reason = art.stop_reason or "budget"
            art.scope.cancel()

    # ------------------------------------------------------------------ background

    async def _board_loop(self) -> None:
        while True:
            await anyio.sleep(BOARD_SCAN_SECONDS)
            await self._scan_boards()

    async def scan_boards(self) -> None:
        await self._scan_boards()

    async def _scan_boards(self) -> None:
        # several callers (the board loop, agents going to sleep, quiesce) may scan at once
        if self._scan_lock is None:
            self._scan_lock = anyio.Lock()
        async with self._scan_lock:
            for rt in self.teams:
                if rt.scanner is None:
                    continue
                try:
                    before = len(self.log.messages)
                    await rt.scanner.scan()
                    if rt.notice_board:
                        for m in self.log.messages[before:]:
                            if m.channel == "board":
                                for r in m.delivered_to:
                                    if r in rt.bus.unread:
                                        rt.bus.unread[r].append(m.id)
                except Exception as ex:  # a failed scan must not end the run
                    transcript().info({"error": str(ex)[:500]}, source="swarm.board_scan_error")

    async def _final_scan(self) -> None:
        with contextlib.suppress(Exception):
            await self._scan_boards()

    async def _stop_loop(self) -> None:
        while True:
            await anyio.sleep(STOP_POLL_SECONDS)
            monitor_reason = monitor_stop_requested()
            user_reason = None if monitor_reason else self._stop_file()
            if (monitor_reason or user_reason) and not self.stopping:
                self.stop_source = "monitor" if monitor_reason else "user"
                self.request_stop(monitor_reason or user_reason or "")

    def _stop_file(self) -> str | None:
        if self.run_dir is None:
            return None
        path = self.run_dir.root / STOP_FILE
        if path.exists():
            return path.read_text().strip() or "stop requested by user"
        return None

    def _cost_cap_reached(self, why: str) -> None:
        """The dollar ledger refused a call: wind the whole run down cleanly."""
        if not self.stopping:
            self.stop_source = "cost"
            self.request_stop(why)

    def request_stop(self, reason: str) -> None:
        """Stop every agent gracefully, then cancel any still running after a grace period.

        react agents stop at their next turn (on_continue); inspect-swe agents get a final
        empty reply from their bridge filter, which ends their session.
        """
        if self.stopping:
            return
        self.stop_reason = reason
        add_problem(f"run stopped early: {reason}")
        transcript().info({"reason": reason}, source="swarm.stop")
        if self.background is not None:
            self.background.start_soon(self._hard_stop)

    async def _hard_stop(self) -> None:
        await anyio.sleep(STOP_GRACE_SECONDS)
        for art in self.agents.values():
            if not art.done and art.scope is not None:
                art.stop_reason = "stopped"
                art.scope.cancel()

    async def renew_leases(self) -> None:
        """Touch each container's lease file; if this process dies, the containers stop themselves."""
        for rt in self.teams:
            if rt.sandbox is not None:
                with contextlib.suppress(Exception):
                    await rt.sandbox.exec(["/bin/touch", LEASE_FILE], user="root", timeout=30)

    async def _lease_loop(self) -> None:
        while True:
            await self.renew_leases()
            await anyio.sleep(LEASE_RENEW_SECONDS)

    async def _status_loop(self) -> None:
        while True:
            self._update_status()
            await anyio.sleep(STATUS_SECONDS)

    # ------------------------------------------------------------------ results

    def agent_usage(self) -> dict[str, dict[str, Any]]:
        out = {}
        for name, art in self.agents.items():
            usage = usage_of(art.meter) if art.meter is not None else ModelUsage()
            out[name] = {
                "tokens": usage.total_tokens,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "usd": usage.total_cost,
                "stop_reason": art.stop_reason or ("running" if art.running else "not started"),
            }
        return out

    def run_cost(self) -> CostSummary:
        """Cost of the whole run so far: finished epochs plus this one."""
        return add_costs([*self.hooks.finished_costs, self.cost_summary()])

    def cost_summary(self) -> CostSummary:
        """Cost of this sample (epoch) only."""
        usage = self.agent_usage()
        by_model: dict[str, float | None] = {}
        unpriced: set[str] = set()
        total = CostSummary(usd=0.0)
        for name, u in usage.items():
            model = self.agents[name].info.model
            total.tokens += u["tokens"]
            total.input_tokens += u["input_tokens"]
            total.output_tokens += u["output_tokens"]
            total.by_agent[name] = u["usd"]
            if u["usd"] is None:
                if u["tokens"]:
                    unpriced.add(model)
            else:
                by_model[model] = (by_model.get(model) or 0.0) + u["usd"]
                total.usd = (total.usd or 0.0) + u["usd"]
        total.by_model = by_model
        total.unpriced_models = sorted(unpriced)
        if unpriced:
            total.usd = None
        return total

    def _write_store(self, state: TaskState) -> None:
        store().set("swarm_messages", [m.model_dump(mode="json") for m in self.log.messages])
        store().set("swarm_agent_usage", self.agent_usage())
        store().set("swarm_attribution", {n: a.filter.counts for n, a in self.agents.items() if a.filter})
        swarm_meta = dict(state.metadata.get("swarm", {}))
        swarm_meta["agents"] = [a.model_dump(mode="json") for a in self.infos()]
        state.metadata["swarm"] = swarm_meta
        state.metadata["swarm_outcome"] = self.outcome()

    def outcome(self) -> dict[str, Any]:
        """How the sample ended: "ok", or why not (read by the runner from sample summaries)."""
        problems = list(store().get("swarm_problems", []))
        reasons = {name: art.stop_reason or "not started" for name, art in self.agents.items()}
        crashed = [r for r in reasons.values() if r.split(":")[0] in ("crashed", "terminated", "not started")]
        if self.sample_error:
            outcome = "sample_error"
            problems.append(f"sample error: {self.sample_error}")
        elif self.stop_source == "monitor":
            outcome = "monitor_stop"
        elif self.stop_source == "user":
            outcome = "user_stop"
        elif self.stop_source == "cost":
            outcome = "cost_cap"
        elif self.gateway_down:
            outcome = "gateway_down"  # model access and attribution evidence lost for some agents
        elif crashed:
            outcome = "agent_errors"
        elif problems:
            outcome = "problems"
        else:
            outcome = "ok"
        return {
            "ok": outcome == "ok",
            "outcome": outcome,
            "problems": problems,
            "agents": reasons,
            "ended_because": self.ended_because(),
        }

    def ended_because(self) -> str:
        """One plain line on why the run ended (for the report's "how it ended")."""
        if self.stop_reason:
            return f"stopped: {self.stop_reason}"
        if self.sample_error == "cancelled":
            return "the run's time limit was reached (or it was cancelled)"
        if self.sample_error:
            return f"the run failed: {self.sample_error}"
        if self.wake.end_reason:
            return self.wake.end_reason
        if all(a.done for a in self.agents.values()):
            return "every agent stopped for good (budget used up or crashed)"
        return "not recorded"

    def _update_status(self, force: bool = False) -> None:
        writer = self.hooks.status
        if writer is None:
            return
        try:
            writer.update(
                force=force,
                compose_project=self.compose_project,
                agents_total=len(self.agents),
                agents_active=sum(1 for a in self.agents.values() if a.running),
                messages=len(self.log.messages),
                swarm_cost=self.run_cost(),
                monitor_flags=self._flag_counts(),
            )
        except Exception:
            pass

    def _flag_counts(self) -> dict[str, int]:
        if self.run_dir is None or not self.run_dir.monitor.exists():
            return {}
        counts: dict[str, int] = {}
        for line in self.run_dir.monitor.read_text().splitlines():
            with contextlib.suppress(ValueError, KeyError, TypeError):
                sev = json.loads(line)["severity"]
                counts[sev] = counts.get(sev, 0) + 1
        return counts


def add_costs(costs: list[CostSummary]) -> CostSummary:
    """Sum cost summaries (a None dollar amount anywhere makes the total unknown)."""
    total = CostSummary(usd=0.0)
    unpriced: set[str] = set()
    for c in costs:
        total.tokens += c.tokens
        total.input_tokens += c.input_tokens
        total.output_tokens += c.output_tokens
        total.usd = None if (total.usd is None or c.usd is None) else total.usd + c.usd
        for key, value in c.by_model.items():
            prev = total.by_model.get(key, 0.0)
            total.by_model[key] = None if (prev is None or value is None) else prev + value
        for key, value in c.by_agent.items():
            prev = total.by_agent.get(key, 0.0)
            total.by_agent[key] = None if (prev is None or value is None) else prev + value
        unpriced.update(c.unpriced_models)
    total.unpriced_models = sorted(unpriced)
    return total


def compose_project_of(env: SandboxEnvironment | None) -> str | None:
    """The Docker Compose project Inspect created for this sample (for ``swarm stop --hard``)."""
    project = getattr(env, "_project", None)
    if project is None and env is not None:
        with contextlib.suppress(Exception):
            from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment

            project = env.as_type(DockerSandboxEnvironment)._project
    return getattr(project, "name", None)


def _empty_state(messages: list) -> AgentState:
    return AgentState(messages=list(messages))


def is_terminate(ex: BaseException) -> bool:
    return type(ex).__name__ in ("TerminateSampleError",)


# ---------------------------------------------------------------------- monitor glue


@contextlib.asynccontextmanager
async def monitor_watch(
    scenario: Scenario,
    run_dir: RunDir | None,
    agents: list[AgentInfo],
    sandboxes: dict[str, SandboxEnvironment],
) -> AsyncIterator[None]:
    try:
        from swarmbench.monitor import watch  # type: ignore[attr-defined]
    except ImportError:
        watch = None
    if watch is None or run_dir is None:
        yield
        return
    async with watch(scenario, run_dir, agents, sandboxes):
        yield


def monitor_stop_requested() -> str | None:
    try:
        from swarmbench.monitor import stop_requested  # type: ignore[attr-defined]
    except ImportError:
        return None
    try:
        return stop_requested()
    except Exception:
        return None


@solver
def swarm_solver(
    scenario: Scenario, run_dir: str | None, run_id: str, dry_run: bool = False, run_start: str | None = None
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        from inspect_ai.model import get_model

        set_dry_run(dry_run)  # guards against any real model call in this sample
        dry_model = get_model() if dry_run else None
        start = datetime.fromisoformat(run_start) if run_start else None
        swarm = Swarm(scenario, RunDir(Path(run_dir)) if run_dir else None, run_id, dry_model, start)
        await swarm.run(state)
        state.completed = True
        return state

    return solve
