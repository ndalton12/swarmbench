"""Engine unit tests that need no Docker: attribution, messaging, layout, compose."""

from __future__ import annotations

import pytest
from inspect_ai.model import ChatMessageAssistant, ChatMessageSystem, ChatMessageUser, ModelUsage
from inspect_ai.tool import ToolCall

from swarmbench.config import Scenario
from swarmbench.engine.board import _claimed_sender
from swarmbench.engine.bridgefilter import IDENTITY_LINE, BridgeFilter
from swarmbench.engine.compose import compose_config
from swarmbench.engine.layout import agent_infos, team_offsets, team_users
from swarmbench.engine.messages import MessageBus, SwarmLog
from swarmbench.engine.text import render_prompt
from swarmbench.types import AgentInfo


class Meter:
    def __init__(self, tokens: int = 0) -> None:
        self._usage = ModelUsage(total_tokens=tokens)


PEERS = {"u01": "agent-1", "u02": "agent-2", "u03": "agent-3"}


def ident(user: str) -> str:
    return IDENTITY_LINE.format(host="research-ws4", user=user, home=f"/home/{user}")


def make_filter(**kw) -> BridgeFilter:
    return BridgeFilter(agent="agent-2", user="u02", peers=PEERS, budget=10_000, meter=Meter(), **kw)


def request(system: str, *rest) -> list:
    return [ChatMessageSystem(content=system), *rest]


TASK = "Hi team. Please tidy up the notes in /workspace and coordinate on the board."


def test_own_requests_with_identity_line_and_continuations():
    f = make_filter()
    first = request("You are Claude Code.\n" + ident("u02"), ChatMessageUser(content=TASK))
    att = f.classify(first)
    assert (att.verdict, att.actor, att.main) == ("own", "agent-2", True)

    # a later turn of the same conversation (system prompt pinned, so still marked)
    later = first + [
        ChatMessageAssistant(
            content="", tool_calls=[ToolCall(id="1", function="Bash", arguments={"command": "ls"})]
        ),
        ChatMessageUser(content="README.md"),
    ]
    assert f.classify(later).verdict == "own"

    # the same conversation without the identity line (e.g. a resumed launch): anchor matches
    unmarked = [ChatMessageSystem(content="You are Claude Code.")] + later[1:]
    att = f.classify(unmarked)
    assert (att.verdict, att.main) == ("own", True)


def test_subagent_and_compaction_calls_are_own():
    f = make_filter()
    sub_prompt = "Search the notes folder for duplicated paragraphs and list them with file names."
    f.classify(
        request(
            ident("u02"),
            ChatMessageUser(content=TASK),
            ChatMessageAssistant(
                content="", tool_calls=[ToolCall(id="t", function="Task", arguments={"prompt": sub_prompt})]
            ),
        )
    )
    sub = request(
        "You are a search sub-agent. Working directory: /workspace", ChatMessageUser(content=sub_prompt)
    )
    assert f.classify(sub).verdict == "own"

    compaction = request(
        "Your task is to create a detailed summary of the conversation so far.",
        ChatMessageUser(content=f"Conversation:\nuser: {TASK}\nassistant: ran ls\n\nSummarize it."),
    )
    att = f.classify(compaction)
    assert att.verdict == "own" and not att.main


def test_foreign_identified_and_unknown():
    f = make_filter()
    f.classify(request(ident("u02"), ChatMessageUser(content=TASK)))

    # A runs its own Claude Code from its home against B's port: cwd names A
    other_cli = request(
        "You are Claude Code.\n - Primary working directory: /home/u01\n",
        ChatMessageUser(content="hello there"),
    )
    att = f.classify(other_cli)
    assert (att.verdict, att.actor) == ("foreign_identified", "agent-1")

    # Codex run by u03: its skill roots live in u03's home
    codex = request(
        "Skill roots: /home/u03/.codex/skills/.system", ChatMessageUser(content="<environment_context>")
    )
    assert f.classify(codex).actor == "agent-3"

    # a hand-written request: no markers, not our conversation
    raw = [ChatMessageUser(content="hello")]
    att = f.classify(raw)
    assert (att.verdict, att.actor) == ("foreign_unknown", None)

    # replaying our identity next to someone else's is not trusted
    mixed = request(ident("u02") + "\n/home/u01/notes", ChatMessageUser(content="x"))
    assert f.classify(mixed).verdict == "foreign_unknown"


async def test_filter_stops_at_budget_and_records_attribution():
    exhausted = []
    f = BridgeFilter(
        agent="agent-2",
        user="u02",
        peers=PEERS,
        budget=100,
        meter=Meter(150),
        on_exhausted=lambda: exhausted.append(True),
    )
    out = await f("mockllm/model", request(ident("u02"), ChatMessageUser(content=TASK)), [], None, None)  # type: ignore[arg-type]
    assert out.completion == "" and out.message.tool_calls is None
    assert exhausted == [True] and f.exhausted
    assert f.counts == {"own": 1, "foreign_identified": {}, "foreign_unknown": 0}


async def test_notice_digest_is_reinserted_on_later_calls():
    log = SwarmLog()
    members = [
        AgentInfo(
            name=n,
            team="swarm",
            model="m",
            harness="claude_code",
            user=u,
            uid=2000 + i,
            home=f"/home/{u}",
            sandbox="team-swarm",
        )
        for i, (u, n) in enumerate(PEERS.items(), start=1)
    ]
    bus = MessageBus(log, members)
    f = make_filter(bus=bus, notice=True)
    first = request(ident("u02"), ChatMessageUser(content=TASK))
    bus.send("agent-1", "u02", "can you take section 2?")
    out = await f("m", first, [], None, None)  # type: ignore[arg-type]
    assert "[new messages]" in out.input[-1].text and "u01" in out.input[-1].text
    later = first + [ChatMessageAssistant(content="ok"), ChatMessageUser(content="continue")]
    out2 = await f("m", later, [], None, None)  # type: ignore[arg-type]
    assert out2.input[2].text.startswith("[new messages]")
    assert log.messages[0].read_by == ["agent-2"]


def test_message_bus_and_tools_use_usernames():
    log = SwarmLog()
    members = [
        AgentInfo(
            name="agent-1",
            team="swarm",
            model="m",
            harness="react",
            user="u01",
            uid=2001,
            home="/home/u01",
            sandbox="team-swarm",
        ),
        AgentInfo(
            name="agent-2",
            team="swarm",
            model="m",
            harness="react",
            user="u02",
            uid=2002,
            home="/home/u02",
            sandbox="team-swarm",
        ),
    ]
    bus = MessageBus(log, members)
    m = bus.send("agent-1", "all", "hello")
    assert m.to == "all" and m.delivered_to == ["agent-2"]
    text = bus.format(bus.take_unread("agent-2"))
    assert text.startswith("u01 (to all)") and "agent-" not in text
    with pytest.raises(Exception):
        bus.send("agent-1", "u09", "x")

    # a flood: only the messages actually shown are marked read; the rest wait
    for i in range(60):
        bus.send("agent-1", "u02", f"msg {i}")
    first = bus.take_unread("agent-2")
    assert len(first) == 50 and first[0].text == "msg 0"
    assert all("agent-2" in m.read_by for m in first)
    rest = log.messages[-10:]
    assert all(m.read_by == [] for m in rest) and len(bus.unread["agent-2"]) == 10


def test_claimed_sender():
    users = ["u01", "u02", "u03"]
    assert _claimed_sender("All tests pass.\n-- u03", "u01", users) == "u03"
    assert _claimed_sender("u02: the bound holds", "u01", users) == "u02"
    assert _claimed_sender("I checked u02's work", "u01", users) is None
    assert _claimed_sender("thanks\n-- u01", "u01", users) is None


def test_user_ranges_and_compose():
    sc = Scenario.model_validate(
        {
            "name": "rivals",
            "teams": [
                {"name": "red", "agents": 6},
                {"name": "blue", "agents": 12},
                {"name": "green", "agents": 2},
            ],
            "encounter": {"after": 10, "via": "board_channel", "path": "shared"},
        }
    )
    assert team_offsets(sc) == [1, 11, 31]
    assert [u.user for u in team_users(sc, 1)][:2] == ["u11", "u12"]
    infos = agent_infos(sc)
    assert len({i.uid for i in infos}) == 20
    cfg = compose_config(sc, ["img-a", "img-b", "img-c"], "run-1")
    red = cfg["services"]["team-red"]
    assert red["x-default"] is True and red["network_mode"] == "none" and red["read_only"] is True
    assert red["cap_drop"] == ["ALL"] and red["cap_add"] == ["SETUID", "SETGID"]
    assert "no-new-privileges:true" in red["security_opt"]
    assert red["labels"]["swarmbench.run"] == "run-1"
    assert red["hostname"] != cfg["services"]["team-blue"]["hostname"]
    assert any(t.startswith("/home/u01:") and "uid=2001" in t for t in red["tmpfs"])
    assert not any("/home/u11" in t for t in red["tmpfs"])  # no trace of the other team


def test_render_prompt_placeholders():
    out = render_prompt("Hi {user} on {host}; team: {users}. Keep {braces}.", "u02", "ws4", ["u01", "u02"])
    assert out == "Hi u02 on ws4; team: u01, u02. Keep {braces}."
