"""Stage 1 of the two-pass judge: ledger, compaction, coverage manifest and
source-bound evidence. Deterministic; no model calls."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from inspect_ai.log import read_eval_log

from swarmbench.judge.compaction import LONG_OUTPUT, compact, cut_output, expand
from swarmbench.judge.evidence import find_quote, verify_quote, workspace_evidence
from swarmbench.judge.extract import extract_sample
from swarmbench.judge.material import build_material
from tests.fixtures import build_mock_log

REAL = Path(__file__).parent / "data" / "realrun"
AGENTS = {"agent-1", "agent-2", "agent-3"}


@pytest.fixture(scope="module")
def real():
    log = next((REAL / "logs").glob("*.eval"))
    sample = read_eval_log(str(log), resolve_attachments=True).samples[0]
    inputs = extract_sample(sample)
    return sample, build_material(sample, inputs, REAL)


def _mock(tmp_path, **kwargs):
    path = build_mock_log(tmp_path, **kwargs)
    sample = read_eval_log(str(path), resolve_attachments=True).samples[0]
    return sample, build_material(sample, extract_sample(sample), None)


# --- the ledger ------------------------------------------------------------------------


def test_every_log_event_is_in_the_ledger_or_explained(real):
    sample, m = real
    assert m.problems == []
    assert m.ledger.unaccounted(sample) == []
    reasons = Counter(v for v in m.ledger.inventory.values() if isinstance(v, str))
    assert reasons["sandbox infrastructure (container exec/read)"] > 1000


def test_resent_context_is_not_added_again(real):
    sample, m = real
    models = [e for e in sample.events if e.event == "model"]
    outputs_with_text = sum(1 for e in models if e.output.message.text.strip())
    kinds = Counter(e.kind for e in m.ledger.events)
    assert kinds["text"] == outputs_with_text  # one per output, none re-added from later inputs
    assert kinds["tool_call"] == kinds["tool_result"] == 38
    resent_chars = sum(len(str(msg.content)) for e in models for msg in e.input)
    assert m.ledger.store.unique_chars() < resent_chars / 8
    # about 40k tokens of unique content, as measured for this run
    assert 30_000 < m.ledger.store.unique_chars() / 4 < 50_000


def test_actors_links_and_key_facts(real):
    _, m = real
    lg = m.ledger
    for e in lg.events:
        if e.kind in ("reasoning", "text", "tool_call", "tool_result"):
            assert e.actor in AGENTS
    links = Counter(link.kind for link in lg.links)
    assert links["call_result"] == 38  # every tool call linked to its result
    assert links["request"] == 45  # every attribution record linked to its model call
    assert links["message_read"] > 0 and links["message_delivery"] > 0
    texts = {e.kind: [] for e in lg.events}
    for e in lg.events:
        texts[e.kind].append(lg.text(e))
    assert any("PROVEN infeasible" in t for t in texts["message"])
    assert any("git checkout" in t for t in texts["tool_call"])
    # the same Claude Code system prompt for three agents is stored once
    big = [e for e in lg.events if e.kind == "system" and len(lg.text(e)) > 7000]
    assert len(big) == 3 and len({e.content for e in big}) == 1


def test_genuine_repeats_and_restarts_are_kept(tmp_path):
    # the same words said in two separate wake sessions are two events, and the
    # second conversation's identical start is marked as a restart
    sample, m = _mock(
        tmp_path,
        agent_texts={"agent-1": "first turn", "agent-2": "hello"},
        sessions={"agent-1": ["same words", "same words"]},
    )
    lg = m.ledger
    said = [e for e in lg.events if e.kind == "text" and lg.text(e) == "same words"]
    assert len(said) == 2 and said[0].content == said[1].content
    assert any(e.kind == "context" and e.meta.get("agent") == "agent-1" for e in lg.events)
    assert lg.unaccounted(sample) == []


def test_foreign_turns_are_attributed_to_the_true_actor(tmp_path):
    _, m = _mock(
        tmp_path,
        agent_texts={"agent-1": "own work", "agent-2": "own work too"},
        foreign_turns=[{"bridge_of": "agent-1", "verdict": "foreign_identified", "actor": "agent-2",
                        "relay_actor": "agent-2", "relay_uid": 2002, "text": "written by agent-2"}],
    )
    lg = m.ledger
    e = next(e for e in lg.events if lg.text(e) == "written by agent-2")
    assert e.actor == "agent-2" and e.owner == "agent-1" and e.basis
    view = {c.id: c.text for c in m.view}
    assert "via agent-1's bridge" in view[e.id]


# --- compaction ---------------------------------------------------------------------------


def test_compaction_keeps_every_event_and_is_reversible(real):
    _, m = real
    lg = m.ledger
    assert [c.id for c in m.view] == [e.id for e in lg.events]
    by_id = lg.by_id()
    for c in m.view:
        e = by_id[c.id]
        if e.kind in ("reasoning", "text", "tool_call", "message"):
            assert not c.cut and lg.text(e) in c.text  # always in full
        if c.cut and e.kind == "tool_result":
            assert len(lg.text(e)) > LONG_OUTPUT and f"fetch {e.id}" in c.text
            assert lg.text(e) in expand(lg, e.id)
    # the 7.6k-character system prompt appears in full once only
    big = next(e for e in lg.events if e.kind == "system" and len(lg.text(e)) > 7000)
    assert sum(lg.text(big) in c.text for c in m.view) == 1
    shown = sum(len(c.text) for c in m.view)
    assert shown < lg.store.unique_chars()


def test_cut_output_keeps_result_lines():
    body = "start\n" + "noise line\n" * 300 + "make: *** [check] Error 2\nexit code 2\n" + "more\n" * 300 + "end"
    shown, cut = cut_output(body)
    assert cut and shown.startswith("start") and shown.endswith("end")
    assert "Error 2" in shown and "exit code 2" in shown
    assert cut_output("short") == ("short", False)


def test_repeated_long_outputs_point_back(tmp_path):
    from swarmbench.judge.ledger import ContentStore, Ledger, LedgerEvent

    lg = Ledger(store=ContentStore())
    long = "x" * 5000
    for i in (1, 2):
        lg.events.append(LedgerEvent(id=f"L000{i}", source=f"s{i}", time=None, kind="tool_result",
                                     actor="agent-1", content=lg.store.put(long)))
    view = compact(lg)
    assert "identical to the text of L0001" in view[1].text
    assert expand(lg, "L0002").endswith(long)


# --- coverage manifest ----------------------------------------------------------------------


def test_manifest_records_who_read_what(real):
    sample, m = real
    ids = [e.id for e in m.ledger.events]
    half = len(ids) // 2
    man = m.manifest
    man.record("chunk-01", "anthropic/claude-opus-5-5", ids[:half])
    problems = man.reconcile(sample)
    assert problems and "not read by any successful judge call" in problems[0]
    man.record("chunk-02", "anthropic/claude-sonnet-5-5", ids[half:], ok=False, note="truncated")
    assert any("failed" in p for p in man.reconcile(sample))
    assert man.unread() == ids[half:]  # a failed call doesn't count as reading
    man.record("chunk-02-retry", "anthropic/claude-sonnet-5-5", ids[half:])
    assert man.unread() == []
    spans = man.spans_by_model()
    assert spans["anthropic/claude-opus-5-5"] == [f"{ids[0]}-{ids[half - 1]}"]
    assert spans["anthropic/claude-sonnet-5-5"] == [f"{ids[half]}-{ids[-1]}"]
    js = man.to_json()
    assert js["source_events_mapped"] > 0 and js["source_events_excluded"]


# --- workspace evidence and quotes --------------------------------------------------------------


def test_workspace_inventory_lists_every_change_with_reasons(real):
    sample, m = real
    ws = m.workspace
    inputs = extract_sample(sample)
    assert len(ws.files) == len(inputs.workspace_changes) == 27
    for f in ws.files:
        assert f.fragment or f.omitted, f.path  # shown, or the reason it isn't
    by_path = {f.path: f for f in ws.files}
    assert "62 symbols total, 63 needed" in by_path["FW-1182/status.md"].fragment
    # deletions are shown: the rev C changelog section was removed
    assert "-## [unreleased] - rev C" in by_path["lb2-protocol/CHANGELOG.md"].fragment
    assert by_path["lb2-protocol/.git/index"].omitted == "binary file"
    text = ws.render()
    assert "W01" in text and "untrusted" in text
    # tool calls that name a changed file are linked to it
    status = by_path["FW-1182/status.md"].id
    assert any(link.kind == "file_ref" and link.dst == status for link in m.ledger.links)


def test_workspace_without_snapshots_says_so():
    changes = [{"path": "/workspace/a.txt", "change": "changed", "type": "file", "agent": "agent-1",
                "team": "swarm"}]
    ws = workspace_evidence(None, changes)
    assert ws.files[0].omitted == "workspace snapshots unavailable"
    assert any("snapshots" in g for g in ws.gaps)


def test_quotes_are_bound_to_event_and_author(real):
    _, m = real
    lg = m.ledger
    hits = find_quote(lg, "PROVEN   infeasible:  with the 17 deployed")
    # agent-3 wrote it; other agents only saw it in tool output (board reads)
    assert {h.author for h in hits} <= {"agent-3", None}
    assert any(h.author is None and h.seen_by == "agent-2" for h in hits)
    first = next(h for h in hits if h.author == "agent-3")
    loc = verify_quote(lg, first.source, "proven infeasible", author="agent-3")
    assert loc is not None and loc.offset >= 0
    assert verify_quote(lg, first.source, "proven infeasible", author="agent-1") is None
    assert verify_quote(lg, first.source, "a sentence nobody wrote") is None
    seen = next(h for h in hits if h.seen_by == "agent-2")
    assert verify_quote(lg, seen.source, "proven infeasible", author="agent-2") is None
    status = next(f for f in m.workspace.files if f.path == "FW-1182/status.md")
    assert verify_quote(lg, status.id, "Do NOT ship this image", workspace=m.workspace) is not None
