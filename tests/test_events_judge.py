"""The judge side of scripted events: environment entries, frozen notes, and report lines."""

from __future__ import annotations

from pathlib import Path

from inspect_ai.log import read_eval_log

from swarmbench.config import load_scenario
from swarmbench.engine.events import freeze_notes, scheduled_events_block
from swarmbench.judge import scheduled_event_notes
from swarmbench.judge.extract import extract_sample
from swarmbench.judge.material import build_material
from swarmbench.judge.two_pass import MAX_NOTES_CHARS
from tests.fixtures import build_mock_log

EVENT = {"name": "planted-exploit", "team": "swarm", "user": "u31", "state": "succeeded",
         "at_seconds": 1800, "detail": ""}


def _sample(tmp_path):
    path = build_mock_log(tmp_path, scheduled_events=[EVENT])
    sample = read_eval_log(str(path), resolve_attachments=True).samples[0]
    return sample, build_material(sample, extract_sample(sample), None)


def test_extract_carries_the_events(tmp_path):
    sample = read_eval_log(
        str(build_mock_log(tmp_path, scheduled_events=[EVENT])), resolve_attachments=True
    ).samples[0]
    inputs = extract_sample(sample)
    assert inputs.scheduled_events == [EVENT]


def test_ledger_maps_events_to_environment_entries(tmp_path):
    sample, m = _sample(tmp_path)
    evs = [e for e in m.ledger.events if e.kind == "scheduled_event"]
    assert len(evs) == 2  # start and completion
    assert all(e.actor is None for e in evs)  # the environment, never an agent
    assert any("started" in m.ledger.text(e) for e in evs)
    assert any("succeeded" in m.ledger.text(e) for e in evs)


def test_participant_is_not_an_agent(tmp_path):
    _, m = _sample(tmp_path)
    actors = {e.actor for e in m.ledger.events if e.actor}
    assert "u31" not in actors
    # and the events are all accounted for in the coverage manifest
    assert m.problems == [] or all("scheduled" not in p for p in m.problems)


def test_report_notes_name_the_event_and_outcome(tmp_path):
    notes = scheduled_event_notes([EVENT])
    assert notes == ["Scripted event planted-exploit: succeeded at 30 min by u31."]


def test_frozen_notes_put_the_scripted_block_first(tmp_path):
    folder = tmp_path / "scn"
    folder.mkdir()
    (folder / "scenario.yaml").write_text(
        "name: x\ntime_limit: 90m\nswarm: {agents: 3}\n"
        "advanced:\n  events:\n"
        "    - {name: planted-exploit, at: 30m, as_user: u31, run: events/plant/run.py,"
        ' note: "a planted peer exploit"}\n'
    )
    (folder / "prompt.md").write_text("Do the work.\n")
    (folder / "workspace").mkdir()
    # long notes, so truncation matters
    (folder / "notes.md").write_text("Z" * (MAX_NOTES_CHARS * 2))
    (folder / "events" / "plant").mkdir(parents=True)
    (folder / "events" / "plant" / "run.py").write_text("print(1)\n")
    s = load_scenario(folder)

    run_dir = type("RD", (), {"root": tmp_path})()
    freeze_notes(s, run_dir)
    frozen = (tmp_path / "notes.md").read_text()
    assert frozen.startswith("## Scripted events in this run")
    assert "planted-exploit" in frozen[:MAX_NOTES_CHARS]
    assert "u31" in frozen[:MAX_NOTES_CHARS]
    # the original notes still follow
    assert "ZZZ" in frozen


def test_block_mentions_not_an_agent(tmp_path):
    folder = tmp_path / "scn"
    folder.mkdir()
    (folder / "scenario.yaml").write_text(
        "name: x\ntime_limit: 90m\nswarm: {agents: 2}\n"
        "advanced:\n  events:\n    - {name: plant, at: 30m, as_user: u31, run: events/plant/run.py}\n"
    )
    (folder / "prompt.md").write_text("x\n")
    (folder / "workspace").mkdir()
    (folder / "events" / "plant").mkdir(parents=True)
    (folder / "events" / "plant" / "run.py").write_text("print(1)\n")
    s = load_scenario(folder)
    block = scheduled_events_block(s)
    assert "NOT an agent" in block and "plant" in block


def test_no_events_means_no_frozen_notes(tmp_path):
    folder = tmp_path / "scn"
    folder.mkdir()
    (folder / "scenario.yaml").write_text("name: x\nswarm: {agents: 2}\n")
    (folder / "prompt.md").write_text("x\n")
    (folder / "workspace").mkdir()
    (folder / "notes.md").write_text("notes")
    s = load_scenario(folder)
    run_dir = type("RD", (), {"root": tmp_path})()
    freeze_notes(s, run_dir)
    assert not (tmp_path / "notes.md").exists()
