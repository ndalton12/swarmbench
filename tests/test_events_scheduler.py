"""The scripted-event scheduler's state machine, driven with fakes (no Docker)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from swarmbench import config
from swarmbench.config import load_scenario
from swarmbench.engine import events as events_mod
from swarmbench.engine.events import EventScheduler


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(events_mod, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(events_mod, "END_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(events_mod, "KILL_GRACE_SECONDS", 0)


class FakeExec:
    def __init__(self, success=True, stdout="", stderr=""):
        self.success, self.stdout, self.stderr = success, stdout, stderr


class FakeSandbox:
    """Answers the handful of shell snippets the scheduler runs, with a controllable process."""

    def __init__(self, *, launch_ok=True, stdout_line="", stderr=""):
        self.launch_ok = launch_ok
        self.alive = True
        self.rc: int | None = None
        self.gone = False
        self.stdout_line = stdout_line
        self.stderr = stderr
        self.killed = False

    async def exec(self, cmd, user=None, timeout=None):
        script = cmd[-1]
        if "setsid" in script:
            return FakeExec(success=self.launch_ok, stderr="" if self.launch_ok else "boom")
        if "kill -0" in script:
            if self.alive:
                return FakeExec(stdout="ALIVE\n")
            if self.rc is not None:
                return FakeExec(stdout=f"DONE\n{self.rc}\n")
            return FakeExec(stdout="GONE\n")
        if "kill -TERM" in script:
            self.killed = True
            return FakeExec(success=True)
        if script.strip().startswith("cat ") and "/stdout" in script:
            return FakeExec(stdout=self.stdout_line)
        if script.strip().startswith("cat ") and "/stderr" in script:
            return FakeExec(stdout=self.stderr)
        return FakeExec()


def _scenario(tmp_path, *, at="30m", agents=3):
    (tmp_path / "scenario.yaml").write_text(
        "name: x\ntime_limit: 90m\n"
        f"swarm: {{agents: {agents}}}\n"
        "advanced:\n  events:\n"
        f"    - {{name: plant, at: {at}, as_user: u31, run: events/plant/run.py}}\n"
    )
    (tmp_path / "prompt.md").write_text("Do the work.\n")
    (tmp_path / "workspace").mkdir(exist_ok=True)
    folder = tmp_path / "events" / "plant"
    folder.mkdir(parents=True)
    (folder / "run.py").write_text("print('{}')\n")
    return load_scenario(tmp_path)


def _swarm(scenario, sandbox, *, agents_done=False, dry=False, stopping=False):
    agent_names = scenario.resolved_teams()[0].agent_names()
    agents = {n: SimpleNamespace(done=agents_done, info=SimpleNamespace(name=n)) for n in agent_names}
    team = SimpleNamespace(
        team=SimpleNamespace(name="swarm"),
        sandbox=sandbox,
        agents=[SimpleNamespace(name=n) for n in agent_names],
    )
    return SimpleNamespace(
        scenario=scenario,
        teams=[team],
        agents=agents,
        started=time.monotonic(),
        stopping=stopping,
        dry_model=object() if dry else None,
        wake=SimpleNamespace(touch=lambda: None),
    )


async def _run_one(sched, swarm):
    event = swarm.scenario.advanced.events[0]
    await sched._run_one(swarm.teams[0], event)


async def test_succeeds_when_the_script_exits_zero(tmp_path):
    sc = _scenario(tmp_path, at="1s")
    sb = FakeSandbox(stdout_line='{"outcome": "accepted"}')
    swarm = _swarm(sc, sb)
    sched = EventScheduler(swarm)
    sched.states[("swarm", "plant")].at = 0.0  # fire immediately

    async def exit_soon():
        import anyio

        await anyio.sleep(0.03)
        sb.alive, sb.rc = False, 0

    import anyio

    async with anyio.create_task_group() as tg:
        tg.start_soon(exit_soon)
        tg.start_soon(_run_one, sched, swarm)
    st = sched.states[("swarm", "plant")]
    assert st.state == "succeeded" and st.rc == 0
    assert "accepted" in st.stdout


async def test_failed_when_the_script_exits_nonzero(tmp_path):
    sc = _scenario(tmp_path)
    sb = FakeSandbox()
    sb.alive, sb.rc = False, 1
    swarm = _swarm(sc, sb)
    sched = EventScheduler(swarm)
    sched.states[("swarm", "plant")].at = 0.0
    await _run_one(sched, swarm)
    st = sched.states[("swarm", "plant")]
    assert st.state == "failed" and st.rc == 1 and "exit code 1" in st.detail


async def test_skipped_when_the_run_is_stopping(tmp_path):
    sc = _scenario(tmp_path)
    swarm = _swarm(sc, FakeSandbox(), stopping=True)
    sched = EventScheduler(swarm)
    sched.states[("swarm", "plant")].at = 0.0
    await _run_one(sched, swarm)
    assert sched.states[("swarm", "plant")].state == "skipped"


async def test_skipped_when_no_agents_remain(tmp_path):
    sc = _scenario(tmp_path)
    swarm = _swarm(sc, FakeSandbox(), agents_done=True)
    sched = EventScheduler(swarm)
    sched.states[("swarm", "plant")].at = 0.0
    await _run_one(sched, swarm)
    st = sched.states[("swarm", "plant")]
    assert st.state == "skipped" and "no agents" in st.detail


async def test_launch_failure_is_recorded(tmp_path):
    sc = _scenario(tmp_path)
    swarm = _swarm(sc, FakeSandbox(launch_ok=False))
    sched = EventScheduler(swarm)
    sched.states[("swarm", "plant")].at = 0.0
    await _run_one(sched, swarm)
    assert sched.states[("swarm", "plant")].state == "failed"


async def test_interrupted_at_end_of_run(tmp_path):
    sc = _scenario(tmp_path)
    sb = FakeSandbox()  # stays alive forever
    swarm = _swarm(sc, sb)
    sched = EventScheduler(swarm)
    st = sched.states[("swarm", "plant")]
    await sched._launch(swarm.teams[0], sc.advanced.events[0], st)
    assert st.state == "running"
    await sched.finish()
    assert st.state == "interrupted" and sb.killed


async def test_pending_event_holds_quiescence(tmp_path):
    sc = _scenario(tmp_path, at="30m")
    sched = EventScheduler(_swarm(sc, FakeSandbox()))
    assert sched.pending_before(10.0) is True  # 30 min event still to come at 10 s in
    sched.states[("swarm", "plant")].state = "succeeded"
    assert sched.pending_before(10.0) is False


async def test_pending_event_is_skipped_at_finish(tmp_path):
    sc = _scenario(tmp_path)
    sched = EventScheduler(_swarm(sc, FakeSandbox()))
    await sched.finish()  # never launched
    assert sched.states[("swarm", "plant")].state == "skipped"


async def test_finish_collects_a_just_finished_event_rather_than_killing_it(tmp_path):
    sc = _scenario(tmp_path)
    sb = FakeSandbox(stdout_line='{"outcome": "accepted"}')
    swarm = _swarm(sc, sb)
    sched = EventScheduler(swarm)
    st = sched.states[("swarm", "plant")]
    await sched._launch(swarm.teams[0], sc.advanced.events[0], st)
    assert st.state == "running"
    sb.alive, sb.rc = False, 0  # it finished right as the run is ending
    await sched.finish()
    assert st.state == "succeeded" and not sb.killed  # collected, not killed/interrupted


async def test_events_sharing_a_participant_use_separate_run_dirs(tmp_path):
    sc = _scenario(tmp_path)
    sched = EventScheduler(_swarm(sc, FakeSandbox()))
    st = sched.states[("swarm", "plant")]
    assert sched._run_dir(st) == "/run/sched/u31/plant"


async def test_dry_run_accelerates_the_schedule(tmp_path):
    sc = _scenario(tmp_path, at="30m")
    sched = EventScheduler(_swarm(sc, FakeSandbox(), dry=True))
    st = sched.states[("swarm", "plant")]
    assert st.accelerated is True
    assert st.at == events_mod.DRY_RUN_EVENT_AFTER  # not the full 1800 s
    assert config  # keep the import referenced
