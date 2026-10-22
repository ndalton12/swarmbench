"""Scripted events run once at the start, before the agents, driven with a fake sandbox (no Docker)."""

from __future__ import annotations

from types import SimpleNamespace

from swarmbench.config import load_scenario
from swarmbench.engine.events import ScriptedEvents


class FakeExec:
    def __init__(self, success=True, returncode=0, stdout="", stderr=""):
        self.success, self.returncode, self.stdout, self.stderr = success, returncode, stdout, stderr


class FakeSandbox:
    def __init__(self, result=None, raises=None):
        self.result, self.raises, self.calls = result or FakeExec(), raises, []

    async def exec(self, cmd, user=None, timeout=None):
        self.calls.append((cmd, user, timeout))
        if self.raises is not None:
            raise self.raises
        return self.result


def _scenario(tmp_path, *, agents=3):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "scenario.yaml").write_text(
        "name: x\ntime_limit: 90m\n"
        f"swarm: {{agents: {agents}}}\n"
        "advanced:\n  events:\n"
        "    - {name: plant, as_user: u31, run: events/plant/run.py, timeout: 10m}\n"
    )
    (tmp_path / "prompt.md").write_text("Do the work.\n")
    (tmp_path / "workspace").mkdir(exist_ok=True)
    folder = tmp_path / "events" / "plant"
    folder.mkdir(parents=True)
    (folder / "run.py").write_text("print('{}')\n")
    return load_scenario(tmp_path)


def _events(scenario, sandbox):
    team = SimpleNamespace(team=SimpleNamespace(name="swarm"), sandbox=sandbox)
    return ScriptedEvents(SimpleNamespace(scenario=scenario, teams=[team]))


async def test_runs_the_script_as_the_participant_and_keeps_its_outcome(tmp_path):
    sb = FakeSandbox(FakeExec(stdout='plant: submitting\n{"outcome": "accepted", "problem": "sendov_conjecture"}\n'))
    ev = _events(_scenario(tmp_path), sb)
    await ev.run()
    (cmd, user, timeout), = sb.calls
    assert user == "u31" and timeout == 600 and cmd[-1].endswith("/run.py")
    (st,) = ev.states.values()
    assert st.state == "succeeded" and st.rc == 0 and st.detail == "accepted sendov_conjecture"
    assert ev.outcome_lines() == ["Scripted event plant: succeeded at the start by u31 (accepted sendov_conjecture)"]
    assert ev.summary()[0]["state"] == "succeeded"


async def test_a_failing_script_is_recorded_not_fatal(tmp_path):
    ev = _events(_scenario(tmp_path), FakeSandbox(FakeExec(success=False, returncode=3, stderr="boom")))
    await ev.run()
    (st,) = ev.states.values()
    assert st.state == "failed" and st.rc == 3 and st.detail == "exit 3" and st.stderr == "boom"


async def test_a_timeout_or_sandbox_error_is_a_failure(tmp_path):
    for raises, detail in ((TimeoutError(), "timed out after 600 s"), (RuntimeError("no container"), "RuntimeError")):
        ev = _events(_scenario(tmp_path / type(raises).__name__), FakeSandbox(raises=raises))
        await ev.run()
        (st,) = ev.states.values()
        assert st.state == "failed" and st.detail.startswith(detail)


def test_no_events_means_nothing_runs(tmp_path):
    (tmp_path / "scenario.yaml").write_text("name: x\nswarm: {agents: 2}\n")
    (tmp_path / "prompt.md").write_text("Do the work.\n")
    (tmp_path / "workspace").mkdir()
    ev = _events(load_scenario(tmp_path), FakeSandbox())
    assert not ev.enabled and ev.summary() == []


def test_the_orchestrator_runs_events_before_the_agents_start():
    import inspect

    from swarmbench.engine.orchestrator import Swarm

    source = inspect.getsource(Swarm.run)
    assert source.index("await self.events.run()") < source.index("self.started = time.monotonic()")
    assert source.index("await self.events.run()") < source.index("await self._run_agents(")
