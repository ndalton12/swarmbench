"""Wake on activity: an agent that stops is woken by genuine new activity, not scripts."""

from __future__ import annotations

import pytest

from tests.engine_helpers import (
    info_events,
    make_scenario,
    model_inputs_text,
    requires_docker,
    run_mock,
    span_agents,
    tool_results_text,
)

pytestmark = [requires_docker, pytest.mark.docker]


def _wakes(sample, agent):
    return [e.data for e in info_events(sample, "swarm.agent_wake") if e.data["agent"] == agent]


def test_peer_board_post_wakes_a_stopped_agent(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{"swarm.agents": 2, "swarm.messaging": "board", "advanced.extra": {"quiet_period": "12s"}},
    )
    scripts = {
        # u01 finishes early and goes quiet
        "agent-1": [("shell", "echo u01 initial look"), ("final", "nothing more to do")],
        # u02 waits until u01 is asleep, then posts; u01 should wake and continue
        "agent-2": [
            (
                "shell",
                "for i in $(seq 30); do grep -q 'waiting' /dev/null 2>/dev/null; sleep 1; "
                "done 2>/dev/null; true",
            ),
            ("shell", "sleep 14; board post general -m 'u01, can you re-check the totals?'"),
            ("final", "done"),
        ],
    }
    sample, _, _ = run_mock(folder, tmp_path, scripts)

    wakes = _wakes(sample, "agent-1")
    assert wakes, [e.data for e in info_events(sample, "swarm.agent_sleep")]
    assert any(w["message_ids"] for w in wakes)
    # u01's conversation continued with a plain note naming the poster and channel
    text = model_inputs_text(sample, "agent-1")
    assert "[activity on this host]" in text and "u02 posted in #general" in text
    assert "re-check the totals" in text
    # it was woken by a peer, never by its own post
    assert all(
        sample.store["swarm_messages"][mid - 1]["sender"] != "agent-1"
        for w in wakes
        for mid in w["message_ids"]
    )


def test_no_self_wake_and_run_ends_after_quiet(tmp_path):
    import time

    folder = make_scenario(
        tmp_path,
        **{"swarm.agents": 1, "swarm.messaging": "board", "advanced.extra": {"quiet_period": "8s"}},
    )
    # the only agent posts and writes its own files, then stops; nothing else happens
    scripts = {
        "agent-1": [
            ("shell", "board post general -m 'done, posting my summary'"),
            ("shell", "echo mine > /workspace/u01-notes.txt"),
            ("final", "finished"),
        ]
    }
    started = time.monotonic()
    sample, _, _ = run_mock(folder, tmp_path, scripts)
    elapsed = time.monotonic() - started

    assert _wakes(sample, "agent-1") == []  # its own post and file never woke it
    assert info_events(sample, "swarm.agent_sleep")  # it did go to sleep
    stopped = {e.data["agent"]: e.data["reason"] for e in info_events(sample, "swarm.agent_stopped")}
    assert stopped == {"agent-1": "finished"}
    assert elapsed < 60  # the run ended after the short quiet period, not at the time limit


def test_claude_code_resumes_same_session_on_wake(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 2,
            "swarm.messaging": "board",
            "advanced.extra": {"harnesses": ["claude_code", "react"], "quiet_period": "12s"},
        },
    )
    scripts = {
        # u01 (Claude Code) records a marker, stops, then after waking writes a second file
        "agent-1": [
            ("shell", "echo first > /workspace/u01-first.txt"),
            ("final", "done for now"),
            ("shell", "echo second > /workspace/u01-second.txt"),
            ("final", "done again"),
        ],
        "agent-2": [
            ("shell", "sleep 14; board post general -m 'u01 please continue'"),
            ("final", "done"),
        ],
    }
    sample, _, _ = run_mock(folder, tmp_path, scripts)
    assert _wakes(sample, "agent-1")
    # the file written after waking shows the resumed session kept working
    changed = {c["path"] for c in sample.store["swarm_workspace_diff"]["swarm"]["changes"]}
    assert "/workspace/u01-first.txt" in changed and "/workspace/u01-second.txt" in changed

    # after waking, the model request continues the SAME conversation: its first user message
    # is still the original task (Claude Code replays its session history through --resume)
    owners = span_agents(sample)
    wake_time = _wakes(sample, "agent-1")[0]
    first_texts = [
        next((m.text for m in e.input if m.role == "user"), "")
        for e in sample.events
        if e.event == "model" and owners.get(e.span_id or "") == "agent-1" and e.input
    ]
    assert first_texts and all("tidying up the notes" in t for t in first_texts)  # shared across the resume
    assert sample.store["swarm_agent_usage"]["agent-1"]["stop_reason"] == "finished"
