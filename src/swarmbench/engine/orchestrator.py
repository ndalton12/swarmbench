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
from inspect_ai.agent import run
from inspect_ai.log import transcript
from inspect_ai.model import ChatMessageUser, Model, ModelUsage
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import LimitExceededError, SandboxEnvironment, sandbox, store, token_limit

from swarmbench.config import ResolvedTeam, Scenario
from swarmbench.paths import RunDir
from swarmbench.types import AgentInfo, CostSummary

from .board import BoardScanner
from .bridgefilter import BridgeFilter, usage_of
from .context import set_current_agent
from .harness import build_agent
from .layout import OPS_UID, OPS_USER, agent_infos, team_hostname, team_sandbox
from .messages import MessageBus, SwarmLog
from .mock import MockSwarmModel, default_script
from .ports import PortAllocator
from .setup import prepare_container
from .text import render_dates, render_prompt

BOARD_SCAN_SECONDS = 2.0
STOP_POLL_SECONDS = 1.0
STATUS_SECONDS = 3.0
STOP_GRACE_SECONDS = 20.0
BUDGET_GRACE_SECONDS = 30.0
STOP_FILE = "stop_requested"
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


@dataclass
class AgentRuntime:
    info: AgentInfo
    team: TeamRuntime
    prompt: str
    meter: Any = None
    filter: BridgeFilter | None = None
    scope: anyio.CancelScope | None = None
    running: bool = False
    done: bool = False
    stop_reason: str | None = None


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
        try:
            async with monitor_watch(self.scenario, self.run_dir, self.infos(), sandboxes):
                async with anyio.create_task_group() as background:
                    self.background = background
                    background.start_soon(self._board_loop)
                    background.start_soon(self._stop_loop)
                    background.start_soon(self._status_loop)
                    if self.scenario.encounter is not None:
                        from .encounter import run_encounter

                        background.start_soon(run_encounter, self)
                    try:
                        await self._run_agents(background)
                    finally:
                        background.cancel_scope.cancel()
        finally:
            with anyio.CancelScope(shield=True):
                await self._final_scan()
                self._write_store(state)
                self._update_status(force=True)

    async def _prepare_team(self, rt: TeamRuntime) -> None:
        assert rt.sandbox is not None
        await prepare_container(rt.sandbox, rt.agents, rt.hostname, rt.board)
        known = {OPS_UID: OPS_USER}
        rt.scanner = BoardScanner(self.log, rt.sandbox, rt.agents, known)
        await rt.scanner.scan()  # baseline: posts that exist before anyone starts

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
                if art.info.harness == "react":
                    art.running = True
                    agents_tg.start_soon(self._run_agent, art, background)
                else:
                    art.running = True
                    port = await self.allocator.start_with_port(
                        art.info.sandbox,
                        art.info.harness,
                        start=lambda art=art: agents_tg.start_soon(self._run_agent, art, background),
                        finished=lambda art=art: art.done,
                    )
                    art.info.bridge_port = port
            if self.hooks.on_start is not None:
                result = self.hooks.on_start(self)
                if hasattr(result, "__await__"):
                    await result

    async def _run_agent(self, art: AgentRuntime, background: anyio.abc.TaskGroup) -> None:
        info = art.info
        set_current_agent(info.name)
        budget = art.team.team.per_agent_tokens
        reason = "finished"
        is_react = info.harness == "react"
        art.meter = token_limit(budget if is_react else None)
        if not is_react:
            art.filter = BridgeFilter(
                agent=info.name,
                user=info.user,
                peers={a.user: a.name for a in art.team.agents},
                budget=budget,
                meter=art.meter,
                bus=art.team.bus,
                notice=art.team.direct and art.team.notice_direct,
                on_exhausted=lambda: background.start_soon(self._cancel_later, art, BUDGET_GRACE_SECONDS),
                should_stop=lambda: self.stopping,
            )
        agent = build_agent(
            info,
            art.team.team,
            hostname=art.team.hostname,
            default_sandbox=self.default_sandbox,
            bus=art.team.bus,
            direct=art.team.direct,
            notice=art.team.notice_direct and art.team.direct,
            should_stop=lambda: self.stopping,
            bridge_filter=art.filter,
            compaction=self.scenario.advanced.compaction,
            dry_model=self.dry_model,
        )
        messages = [ChatMessageUser(content=art.prompt)]
        with anyio.CancelScope() as scope:
            art.scope = scope
            try:
                if is_react:
                    _, limit_error = await run(agent, messages, limits=[art.meter], name=info.name)
                    if limit_error is not None:
                        reason = "budget"
                else:
                    with art.meter:
                        await run(agent, messages, name=info.name)
                    if art.filter is not None and art.filter.exhausted:
                        reason = "budget"
            except LimitExceededError:
                raise  # sample-level limits (time, tokens, cost) end the whole run
            except Exception as ex:
                if is_terminate(ex):
                    raise
                reason = f"crashed: {type(ex).__name__}: {str(ex)[:500]}"
                add_problem(f"{info.name} crashed: {type(ex).__name__}: {str(ex)[:300]}")
        if scope.cancelled_caught:
            reason = art.stop_reason or "stopped"
        if self.stopping and reason == "finished":
            reason = "stopped"
        art.stop_reason = reason
        art.done = True
        art.running = False
        transcript().info({"agent": info.name, "reason": reason}, source="swarm.agent_stopped")

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

    async def _scan_boards(self) -> None:
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
            reason = monitor_stop_requested() or self._stop_file()
            if reason and not self.stopping:
                self.request_stop(reason)

    def _stop_file(self) -> str | None:
        if self.run_dir is None:
            return None
        path = self.run_dir.root / STOP_FILE
        if path.exists():
            return path.read_text().strip() or "stop requested by user"
        return None

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

    def cost_summary(self) -> CostSummary:
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
                swarm_cost=self.cost_summary(),
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


def compose_project_of(env: SandboxEnvironment | None) -> str | None:
    """The Docker Compose project Inspect created for this sample (for ``swarm stop --hard``)."""
    project = getattr(env, "_project", None)
    if project is None and env is not None:
        with contextlib.suppress(Exception):
            from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment

            project = env.as_type(DockerSandboxEnvironment)._project
    return getattr(project, "name", None)


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

        dry_model = get_model() if dry_run else None
        start = datetime.fromisoformat(run_start) if run_start else None
        swarm = Swarm(scenario, RunDir(Path(run_dir)) if run_dir else None, run_id, dry_model, start)
        await swarm.run(state)
        state.completed = True
        return state

    return solve
