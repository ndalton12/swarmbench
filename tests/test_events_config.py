"""Validation of timed scripted events (``advanced.events``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmbench.config import load_scenario


def write(tmp_path: Path, yaml_text: str) -> Path:
    (tmp_path / "scenario.yaml").write_text(yaml_text)
    (tmp_path / "prompt.md").write_text("Do the work.\n")
    (tmp_path / "workspace").mkdir(exist_ok=True)
    return tmp_path


BASE = """\
name: x
time_limit: 90m
swarm: {agents: 3}
advanced:
  events:
%s
"""


def _event(**over):
    fields = {"name": "plant", "at": "30m", "as_user": "u31", "run": "events/plant/run.py"}
    fields.update(over)
    return "    - {" + ", ".join(f"{k}: {v}" for k, v in fields.items()) + "}\n"


def test_valid_event(tmp_path):
    s = load_scenario(write(tmp_path, BASE % _event(note='"a planted peer"')))
    (ev,) = s.advanced.events
    assert ev.name == "plant" and ev.at == 1800 and ev.as_user == "u31"
    assert ev.timeout == 900  # default 15m
    assert ev.run == "events/plant/run.py"


def test_as_user_collides_with_an_agent(tmp_path):
    with pytest.raises(Exception, match="agent"):
        load_scenario(write(tmp_path, BASE % _event(as_user="u02")))


def test_as_user_cannot_be_an_existing_account(tmp_path):
    with pytest.raises(Exception, match="already an account"):
        load_scenario(write(tmp_path, BASE % _event(as_user="ops")))


def test_bad_duration_is_rejected(tmp_path):
    with pytest.raises(Exception):
        load_scenario(write(tmp_path, BASE % _event(at="soon")))


def test_event_after_the_time_limit_is_rejected(tmp_path):
    with pytest.raises(Exception, match="before the time limit"):
        load_scenario(write(tmp_path, BASE % _event(at="200m")))


def test_run_must_be_under_events(tmp_path):
    with pytest.raises(Exception, match="events/<name>/<script>"):
        load_scenario(write(tmp_path, BASE % _event(run="run.py")))


def test_run_two_components_is_rejected(tmp_path):
    with pytest.raises(Exception, match="events/<name>/<script>"):
        load_scenario(write(tmp_path, BASE % _event(run="events/run.py")))


def test_run_outside_events_is_rejected(tmp_path):
    with pytest.raises(Exception, match="events/<name>/<script>"):
        load_scenario(write(tmp_path, BASE % _event(run="protected/plant/run.py")))


def test_duplicate_event_names_are_rejected(tmp_path):
    two = _event() + _event(run="events/plant/other.py")
    with pytest.raises(Exception, match="unique"):
        load_scenario(write(tmp_path, BASE % two))


def test_as_user_cannot_be_a_service(tmp_path):
    yaml_text = (
        "name: x\ntime_limit: 90m\nswarm: {agents: 2}\n"
        "services:\n  - {name: grid, command: server.py}\n"
        "advanced:\n  events:\n" + _event(as_user="grid")
    )
    with pytest.raises(Exception, match="service"):
        load_scenario(write(tmp_path, yaml_text))
