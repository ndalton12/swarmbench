"""Transcript links in the judge's report.

- every evidence item and every record entry the judge's words cite keeps the Inspect event it came from;
- report.md links each quote and citation to that event in a running ``inspect view``, with its clock time;
- the score in the Inspect log cites evidence as [E012] with Inspect's ``scanner_references`` (the
  viewer's own citation links, as Scout and Petri use) and links record entries within the viewer;
- a report written before links existed renders exactly as it did.
Mock and replay only."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import unquote

import pytest
from inspect_ai.log import read_eval_log

import swarmbench.judge as J
from swarmbench.judge import judge_run
from swarmbench.judge.cite import entry_refs
from swarmbench.judge.report import (
    VIEWER_URL,
    _decode_json_fragment,
    _sentences,
    cited_evidence,
    prose_text,
    render_markdown,
)
from swarmbench.types import Concern, EntryRef, EvidenceItem, JudgeReport, TurningPoint
from tests.data.monitor_fp import make_recording as FP
from tests.test_judge_cite import _material

T0 = datetime(2026, 10, 23, 23, 0, 0, tzinfo=timezone.utc)


def _report(**kw) -> JudgeReport:
    base = dict(run_id="2026-10-23T224732_x", scenario="x", sample_id="x-1", epoch=1, verdict="severe",
                headline="Bad.", summary="Things happened.", log_file="2026-10-23T22-47-36+00-00_swarm_ab.eval")
    return JudgeReport(**(base | kw))


def _item(n: int, event: str | None, minutes: float, text: str = "local notation x") -> EvidenceItem:
    return EvidenceItem(id=f"E{n:03d}", entry=f"L{n:04d}", text=text, author="agent-6", kind="tool_call",
                        label=f"agent-6, command, {minutes} min in", time=T0.replace(minute=int(minutes)),
                        event=event)


def _concern(explanation: str, eid: str = "E001") -> Concern:
    return Concern(behavior="tampered with a checker", severity="severe", agents=["agent-6"],
                   explanation=explanation,
                   evidence=[{"role": "act", "source": "L0001", "author": "agent-6", "text": "local notation x",
                              "id": eid, "label": "agent-6, command, 40.0 min in"}],
                   by_agent=[{"agent": "agent-6", "level": 4, "intent": "deliberate", "disclosed": False,
                              "explanation": "Redefined the term. The grader took it. It said nothing. "
                                             "[act L0007, E002; outcome L0008]"}])


def _url(event: str) -> str:
    return (f"{VIEWER_URL}/#/logs/2026-10-23T22-47-36%2B00-00_swarm_ab.eval/samples/sample/x-1/1/"
            f"transcript?event={event}")


# --- report.md ---------------------------------------------------------------------------------------


def test_quotes_and_citations_link_to_their_event_with_the_clock_time():
    r = _report(concerns=[_concern("It cheated (E001).")],
                evidence=[_item(1, "evA", 40.0), _item(2, "evB", 41.0)],
                entries={"L0007": EntryRef(event="evC", time=T0, label="agent-6, command, 42.5 min in"),
                         "L0008": EntryRef(event="evA", time=T0, label="agent-6, command output, 40.2 min in")})
    md = render_markdown([r], links="url")
    # the quote's label is a link to its event, with the clock time
    assert f"> local notation x\n> — [agent-6, command, 40.0 min in, 23:40:00 UTC]({_url('evA')})" in md
    # the per-agent bullet keeps the citations of the sentences it leaves out (judges cite at the end)
    bullet = next(ln for ln in md.splitlines() if ln.startswith("- **agent-6**"))
    assert "It said nothing" not in bullet
    assert bullet.endswith(f"([42.5 min in]({_url('evC')}); [41.0 min in]({_url('evB')}); "
                           f"[40.2 min in]({_url('evA')}))")
    assert "L0007" not in md.split("## Technical notes")[0] and "E002" not in md.split("## Technical notes")[0]
    # how to open the links is said once, at the top
    assert md.count("`swarm view runs/2026-10-23T224732_x`") == 1


def test_one_link_per_event_and_at_most_four_per_citation():
    items = [_item(i, f"ev{i}", 40 + i) for i in range(1, 7)]
    same = EntryRef(event="ev1", time=T0, label="agent-6, private reasoning, 41.0 min in")
    r = _report(summary="It cheated (E001, L0099, E002, E003, E004, E005).", evidence=items,
                entries={"L0099": same})
    (line,) = [ln for ln in render_markdown([r], links="url").splitlines() if ln.startswith("It cheated")]
    assert line.count("](") == 4 and line.endswith("; …).")
    assert line.count("event=ev1") == 1  # L0099 is the same event as E001


def test_a_report_without_events_renders_as_before():
    """A report written before links existed: ids are dropped, nothing is linked."""
    r = _report(concerns=[_concern("It cheated (E001).")], evidence=[_item(1, None, 40.0)], log_file=None)
    assert render_markdown([r], links="url") == render_markdown([r])
    assert "](" not in render_markdown([r], links="url") and "E001" not in render_markdown([r]).split("## Tech")[0]


def test_a_citation_cut_by_truncation_leaves_no_debris():
    r = _report(evidence=[_item(1, "evA", 40.0)])
    from swarmbench.judge import report as R

    token = R._LINKS.set(R._Links.of("url", r))
    try:
        out = _sentences("A long sentence " + "x" * 50 + " (E001) more.", n=1, limit=40)
    finally:
        R._LINKS.reset(token)
    assert "" not in out and "" not in out and out.startswith("A long sentence")


def test_tool_output_recorded_as_json_is_shown_as_its_text():
    assert _decode_json_fragment(r"ACCEPTED\n\t\u2194 done") == "ACCEPTED\n\t↔ done"
    assert _decode_json_fragment(r'{"output": "ok\n"}') == "ok\n"  # a quote from the JSON's own edges
    assert _decode_json_fragment(r"smile \ud83d\ude00") == "smile 😀"  # a surrogate pair is one character
    for unchanged in (r"lone \ud83d here", r'a "quoted" \n bit', "no escapes"):
        assert _decode_json_fragment(unchanged) == unchanged
    out = _item(1, "evA", 40.0, text=r"a\n\tb \u2203")
    out.kind, out.json_text = "tool_result", True
    r = _report(turning_points=[TurningPoint(title="t", quote=out.text, evidence_id="E001")], evidence=[out])
    assert "> a b ∃\n" in render_markdown([r], links="url")


def test_only_output_recorded_as_json_is_decoded():
    """A backslash in a command, in plain tool output or in an old report is shown as it is."""
    raw = _item(1, "evA", 40.0, text=r"pattern = r'\bword\b' in C:\new\test.py")
    r = _report(turning_points=[TurningPoint(title="t", quote=raw.text, evidence_id="E001")], evidence=[raw])
    for kind in ("tool_call", "tool_result"):  # plain tool output is not JSON
        raw.kind = kind
        assert "> " + raw.text + "\n" in render_markdown([r], links="url")
    raw.json_text, raw.event = True, None  # an old report: no links, no decoding
    assert "> " + raw.text + "\n" in render_markdown([r], links="url")


def test_evidence_knows_whether_its_entry_is_json(tmp_path):
    from swarmbench.judge.cite import EvidenceTable, is_json_document

    assert is_json_document('{"output": "ok\\n"}') and not is_json_document("ok {") \
        and not is_json_document('["a"]') and not is_json_document(r"r'\bword\b'")
    _, _, m = _material(FP.HERE)
    table = EvidenceTable(m.ledger, m.workspace)
    for e in m.ledger.events:
        body = m.ledger.text(e)
        if body:
            item = table.add(e.id, 0, min(len(body), 20), "test")
            assert item.json_text == (e.kind == "tool_result" and is_json_document(body))


def test_text_that_looks_like_an_internal_token_is_harmless():
    r = _report(summary="odd \ue0000\ue001 text \ue0007\ue001 (E001).", evidence=[_item(1, "evA", 40.0)])
    md = render_markdown([r], links="url")
    (line,) = [ln for ln in md.splitlines() if ln.startswith("odd")]
    assert "\ue000" not in md and line.count("event=evA") == 1


def test_prose_citations_are_kept_as_evidence_and_quotes_are_not_prose():
    r = _report(summary="It cheated.\nE002 shows it.",
                turning_points=[TurningPoint(title="t", quote="error E003 at L0004", evidence_id="E001")])
    items = {i.id: i for i in [_item(n, f"e{n}", n) for n in range(1, 5)]}
    assert [e.id for e in cited_evidence(r, items)] == ["E001", "E002"]
    assert "E003" not in prose_text(r) and "L0004" not in prose_text(r)


def test_a_long_realism_note_never_cuts_a_link():
    r = _report(realism_notes=["x " * 140 + "felt staged (E001)."], evidence=[_item(1, "evA", 40.0)])
    (line,) = [ln for ln in render_markdown([r], links="url").splitlines() if ln.startswith("- Realism")]
    assert line.count("[") == line.count("]") and line.count("(") == line.count(")")


# --- the score in the Inspect log ----------------------------------------------------------------------


def test_the_score_cites_evidence_for_the_viewer_and_links_entries_inside_it():
    r = _report(concerns=[_concern("It cheated (E001).")],
                evidence=[_item(1, "evA", 40.0), _item(2, "evB", 41.0)],
                entries={"L0007": EntryRef(event="evC", time=T0, label="agent-6, command, 42.5 min in")})
    md = J._score_markdown(r)
    assert "> — agent-6, command, 40.0 min in, 23:40:00 UTC [E001]" in md
    assert "[42.5 min in](#/logs/2026-10-23T22-47-36%2B00-00_swarm_ab.eval/samples/sample/x-1/1/transcript" \
           "?event=evC)" in md and "[E002]" in md
    assert VIEWER_URL not in md  # inside the viewer, links stay in the viewer
    refs = J._score_metadata(r)["scanner_references"]
    assert refs == [{"type": "event", "cite": "[E001]", "id": "evA"}, {"type": "event", "cite": "[E002]", "id": "evB"}]


# --- end to end (replay of a real run) ----------------------------------------------------------------


def test_a_judged_run_links_every_quote_to_an_event_in_its_log(tmp_path, monkeypatch):
    rd = FP.make_run_dir(tmp_path)
    monkeypatch.setattr(J, "_resolve_models", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no models")))
    (r,) = judge_run(rd, replay=FP.RECORDING, engine="two-pass")
    log_path = next(rd.logs.glob("*.eval"))
    log = read_eval_log(str(log_path))
    uuids = {e.uuid for e in log.samples[0].events}
    assert r.log_file == log_path.name and r.evidence
    assert all(e.event in uuids for e in r.evidence if e.kind != "file")
    assert all(x.event in uuids for x in r.entries.values())
    md = rd.report_md.read_text()
    linked = re.findall(r"\]\((http://127\.0\.0\.1:7575/#/logs/([^/]+)/samples/sample/([^/]+)/1/transcript"
                        r"\?event=([^)]+))\)", md)
    assert linked and all(unquote(f) == log_path.name and unquote(e) in uuids for _, f, _, e in linked)
    score = log.samples[0].scores[J.JUDGE_SCORE]
    refs = score.metadata["scanner_references"]
    assert refs and all(ref["id"] in uuids and ref["cite"] in score.explanation for ref in refs)


def test_entry_refs_point_at_the_event_each_entry_came_from():
    sample, _, m = _material(FP.HERE)
    ids = [e.id for e in m.ledger.events[:5]]
    refs = entry_refs(f"see {ids[0]} and [act {ids[1]}, {ids[2]}] and L99999", m.ledger)
    assert list(refs) == ids[:3]
    uuids = {e.uuid for e in sample.events}
    by_id = m.ledger.by_id()
    for lid, ref in refs.items():
        assert ref.event in uuids and by_id[lid].source.startswith(ref.event + "#") and "min in" in ref.label
