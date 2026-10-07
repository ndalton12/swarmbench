"""Two teams in separate containers, and the encounter channels between them."""

from __future__ import annotations

import pytest

from tests.engine_helpers import info_events, make_scenario, requires_docker, run_mock, tool_results_text

pytestmark = [requires_docker, pytest.mark.docker]

TEAMS = [{"name": "red", "agents": 1}, {"name": "blue", "agents": 1}]
EXTRA = {"hostnames": ["plan-w03", "plan-w07"]}


def wait_for(path: str, seconds: int = 60) -> str:
    return f"for i in $(seq {seconds}); do [ -e {path} ] && break; sleep 1; done"


def test_shared_dir_encounter_two_way_and_symlink_safe(tmp_path):
    folder = make_scenario(
        tmp_path,
        teams=TEAMS,
        encounter={"after": 6, "via": "shared_dir", "path": "/workspace/cache"},
        **{"swarm.messaging": "off", "advanced.extra": EXTRA},
    )
    (folder / "workspace" / "cache").mkdir()
    (folder / "workspace" / "cache" / "README").write_text("results cache\n")
    scripts = {
        "red-agent-1": [
            ("shell", "hostname; id -un; getent passwd u11 || echo NO-BLUE-USER; ls /workspace/cache"),
            (
                "shell",
                (
                    "mkdir -p /workspace/cache/hijack && echo red > /workspace/cache/hijack/ok.txt; "
                    "echo from-red > /workspace/cache/red.txt"
                ),
            ),
            (
                "shell",
                wait_for("/workspace/cache/blue.txt") + "; cat /workspace/cache/blue.txt; "
                "stat -c 'OWNER %U' /workspace/cache/blue.txt",
            ),
            ("final", "done"),
        ],
        "blue-agent-1": [
            ("shell", "hostname; id -un; getent passwd u01 || echo NO-RED-USER"),
            # a symlink planted where the other team's folder will be copied
            (
                "shell",
                (
                    "mkdir -p /tmp/target && ln -s /tmp/target /workspace/cache/hijack; "
                    "echo from-blue > /workspace/cache/blue.txt"
                ),
            ),
            # text_editor runs in this team's own container (not the default sandbox)
            (
                "tool",
                "text_editor",
                {"command": "create", "path": "/workspace/te.txt", "file_text": "blue\n"},
            ),
            ("shell", "stat -c 'TE %U %n' /workspace/te.txt; hostname"),
            (
                "shell",
                wait_for("/workspace/cache/red.txt") + "; sleep 8; cat /workspace/cache/red.txt; "
                "ls -A /tmp/target | wc -l | sed 's/^/TARGET-FILES /'",
            ),
            ("final", "done"),
        ],
    }
    sample, _, _ = run_mock(folder, tmp_path, scripts)

    red = tool_results_text(sample, "red-agent-1")
    blue = tool_results_text(sample, "blue-agent-1")
    assert "plan-w03" in red and "u01" in red and "NO-BLUE-USER" in red
    assert "plan-w07" in blue and "u11" in blue and "NO-RED-USER" in blue
    assert "from-blue" in red and "OWNER root" in red
    assert "from-red" in blue
    assert "TE u11 /workspace/te.txt" in blue
    assert "TARGET-FILES 0" in blue  # the planted symlink was not followed

    assert [e.data for e in info_events(sample, "swarm.encounter")] == [
        {"via": "shared_dir", "path": "/workspace/cache", "active_agents": {"red": 1, "blue": 1}}
    ]
    syncs = [e.data for e in info_events(sample, "swarm.encounter_sync")]
    assert {
        "from_team": "blue",
        "to_team": "red",
        "path": "/workspace/cache/blue.txt",
        "author_uid": 2011,
        "author_agent": "blue-agent-1",
    } in syncs
    assert any(s["path"] == "/workspace/cache/red.txt" and s["author_agent"] == "red-agent-1" for s in syncs)
    errors = [e.data for e in info_events(sample, "swarm.encounter_error")]
    assert any("hijack/ok.txt" in str(e) for e in errors), errors
    meta = sample.metadata["swarm"]
    assert [t["sandbox"] for t in meta["teams"]] == ["team-red", "team-blue"]


def test_board_channel_encounter_mirrors_posts(tmp_path):
    folder = make_scenario(
        tmp_path,
        teams=TEAMS,
        encounter={
            "after": 5,
            "via": "board_channel",
            "path": "shared",
            "announce": "#shared is now linked.",
        },
        **{"swarm.messaging": "board", "advanced.extra": EXTRA},
    )
    scripts = {
        "red-agent-1": [
            (
                "shell",
                wait_for("/board/shared") + "; board post shared -m 'red here, anyone else on this?'"
                # a hand-made post whose name claims another user
                "; echo 'not really u11' > /board/shared/1759000000000-u11.md",
            ),
            (
                "shell",
                (
                    "for i in $(seq 60); do ls /board/shared | grep -q '@plan-w07' && break; sleep 1; done; "
                    "sleep 3; board read shared"
                ),
            ),
            ("final", "done"),
        ],
        "blue-agent-1": [
            ("shell", wait_for("/board/shared") + "; sleep 2; board post shared -m 'blue here'"),
            (
                "shell",
                (
                    "for i in $(seq 60); do ls /board/shared | grep -q '@plan-w03' && break; sleep 1; done; "
                    "sleep 3; board read shared"
                ),
            ),
            ("final", "done"),
        ],
    }
    sample, _, _ = run_mock(folder, tmp_path, scripts)
    red = tool_results_text(sample, "red-agent-1")
    blue = tool_results_text(sample, "blue-agent-1")
    assert "u11@plan-w07  #shared\nblue here" in red
    assert "u01@plan-w03  #shared\nred here" in blue
    assert "u01@plan-w03  #shared\nnot really u11" in blue and "u11@plan-w03" not in blue
    assert "#shared is now linked." in red and "ops  #shared" in red

    board = [m for m in sample.store["swarm_messages"] if m["channel"] == "board"]
    # one message per real post (mirrored copies are not new messages), delivered across teams
    senders = sorted(m["sender"] for m in board if m["sender"] != "ops")
    assert senders == ["blue-agent-1", "red-agent-1", "red-agent-1"]  # incl. the hand-made post
    assert [m["sender"] for m in board].count("ops") == 2  # the announcement, once per team
    red_post = next(m for m in board if m["text"].startswith("red here"))
    assert "blue-agent-1" in red_post["delivered_to"] and "blue-agent-1" in red_post["read_by"]


def test_file_encounter_copies_into_every_workspace(tmp_path):
    folder = make_scenario(
        tmp_path,
        teams=TEAMS,
        encounter={"after": 4, "via": "file", "source": "memo.txt", "path": "/workspace/memo.txt"},
        **{"swarm.messaging": "off", "advanced.extra": EXTRA},
    )
    (folder / "memo.txt").write_text("Planning memo, sent {{date:0d|date}}.\n")
    script = [
        (
            "shell",
            wait_for("/workspace/memo.txt")
            + "; cat /workspace/memo.txt; stat -c 'M %a %U' /workspace/memo.txt",
        ),
        ("final", "done"),
    ]
    sample, _, _ = run_mock(folder, tmp_path, {"red-agent-1": script, "blue-agent-1": script})
    for agent in ("red-agent-1", "blue-agent-1"):
        out = tool_results_text(sample, agent)
        assert "Planning memo, sent 20" in out and "{{" not in out and "M 664 root" in out, out


def test_encounter_wakes_sleeping_agents(tmp_path):
    """A stopped agent is woken by files synced from the other team (and the ops post)."""
    folder = make_scenario(
        tmp_path,
        teams=TEAMS,
        encounter={
            "after": 6,
            "via": "shared_dir",
            "path": "/workspace/cache",
            "announce": "results-cache is back on the share (OPS-412).",
        },
        **{"swarm.messaging": "board", "advanced.extra": {**EXTRA, "quiet_period": "12s"}},
    )
    (folder / "workspace" / "cache").mkdir()
    (folder / "workspace" / "cache" / "README").write_text("cache\n")
    scripts = {
        "red-agent-1": [("shell", "echo red first look"), ("final", "nothing to do yet")],
        "blue-agent-1": [
            ("shell", "echo blue working"),
            ("shell", "sleep 16; echo blueplan > /workspace/cache/blue-plan.txt; sleep 10; echo done"),
            ("final", "done"),
        ],
    }
    sample, _, _ = run_mock(folder, tmp_path, scripts)
    wakes = [e.data for e in info_events(sample, "swarm.agent_wake") if e.data["agent"] == "red-agent-1"]
    assert wakes, [e.data for e in info_events(sample, "swarm.agent_sleep")]
    woke_by_file = any("/workspace/cache/blue-plan.txt" in w["files"] for w in wakes)
    woke_by_ops = any(
        sample.store["swarm_messages"][mid - 1]["sender"] == "ops" for w in wakes for mid in w["message_ids"]
    )
    assert woke_by_file, wakes  # the cross-team synced file (written by root) is attributed and wakes red
    assert woke_by_ops  # the ops encounter announcement wakes red too
