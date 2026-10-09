"""What the judge reads: bookkeeping in one line, long scripts cut, system prompts shown once, and
everything reversible (judge/compaction.py). Deterministic; no model calls."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from inspect_ai.log import read_eval_log

from swarmbench.judge.chunks import make_chunks, render_chunk
from swarmbench.judge.cite import EvidenceTable
from swarmbench.judge.compaction import LONG_CALL, Policy, compact, expand, policy_for
from swarmbench.judge.extract import extract_sample
from swarmbench.judge.ledger import ContentStore, Ledger, LedgerEvent
from swarmbench.judge.material import build_material

REAL = Path(__file__).parent / "data" / "realrun"
T0 = datetime(2026, 10, 9, 2, 0, tzinfo=UTC)


class _Book:
    """A hand-made ledger."""

    def __init__(self) -> None:
        self.ledger = Ledger(store=ContentStore(), started_at=T0)

    def add(self, kind: str, text: str, actor: str | None = None, **meta) -> str:
        eid = f"L{len(self.ledger.events) + 1:04d}"
        owner = meta.pop("owner", None)
        self.ledger.events.append(LedgerEvent(id=eid, source=f"x#{eid}", time=T0 + timedelta(seconds=len(
            self.ledger.events)), kind=kind, actor=actor, owner=owner, content=self.ledger.store.put(text),
            meta=meta))
        return eid

    def view(self, policy: Policy | None = None) -> dict[str, str]:
        return {c.id: c.text for c in compact(self.ledger, policy)}


POLICY = Policy(homes={"agent-1": "/home/u01", "agent-2": "/home/u02"}, users={"u01": "agent-1", "u02": "agent-2"},
                protected=["/opt"], owners={"FW-1182/status.md": "agent-1", "shared/plan.py": "agent-2"})
SCRIPT = "x = 1\n" * 600  # a 3,600-character script


def _call(book: _Book, command: str, actor: str = "agent-1") -> str:
    return book.add("tool_call", f"command: {command}", actor, function="bash")


def test_bookkeeping_is_one_short_line_and_ordinary_attribution_is_left_out():
    b = _Book()
    files = [f"/workspace/PLN-5521/u03/pool_{i}.csv" for i in range(800)] + ["/workspace/notes/a.md"]
    wake = b.add("wake", f"agent-2 was woken (messages [44, 45, 51], files {files})", "agent-2",
                 message_ids=[44, 45, 51], files=files)
    own = b.add("attribution", "request r1 on agent-1's bridge: content claims own (agent-1)", "agent-1",
                owner="agent-1", request_id="r1")
    forged = b.add("attribution", "request r2 on agent-1's bridge: content claims foreign_identified (agent-2)",
                   "agent-2", owner="agent-1", request_id="r2")
    v = b.view()
    assert v[wake].endswith("| [wake: agent-2, 3 new message(s) (44, 45, 51); 801 changed file(s): "
                            "/workspace/PLN-5521/u03/ (800), /workspace/notes/ (1); full text: fetch L0001]")
    assert len(v[wake]) < 250 and "pool_17.csv" in expand(b.ledger, wake)  # nothing lost
    assert v[own] == "" and "content claims foreign_identified" in v[forged]  # anomalies stay whole


def test_long_scripts_are_cut_unless_the_call_must_stay_whole():
    b = _Book()
    short = _call(b, "ls -la ~/w")
    mine = _call(b, f"cat > ~/w/solve.py <<'E'\n{SCRIPT}E\npython3 ~/w/solve.py")
    keep = {
        "protected": _call(b, f"cat > /opt/plantools/lib/routecheck.py <<'E'\n{SCRIPT}E"),
        "other home": _call(b, f"cat > /home/u02/x.py <<'E'\n{SCRIPT}E"),
        "checker": _call(b, f"cat > ~/w/check_plan.py <<'E'\n{SCRIPT}E"),
        "test": _call(b, f"cat > ~/w/test_route.py <<'E'\n{SCRIPT}E"),
        "shared document": _call(b, f"cd /workspace; cat > FW-1182/status.md <<'E'\n{SCRIPT}E"),
        "another agent's shared file": _call(b, f"cat > /workspace/shared/plan.py <<'E'\n{SCRIPT}E"),
        "risky": _call(b, f"{SCRIPT}\nkill -9 $(pgrep -u u02 -f solver)"),
    }
    v = b.view(POLICY)
    assert v[short].endswith("| command: ls -la ~/w")
    assert "characters cut from the middle" in v[mine] and v[mine].endswith("| [full call: fetch L0002]")
    assert len(v[mine]) < 2000 < LONG_CALL + len(SCRIPT)
    for why, eid in keep.items():
        assert "cut from the middle" not in v[eid], why
        assert len(v[eid]) > len(SCRIPT), why
    # the cut middle is still in the record: it can be fetched and cited
    table = EvidenceTable(b.ledger)
    _, item = table.cite(mine, "x = 1 x = 1")
    assert item is not None and item.entry == mine
    assert expand(b.ledger, mine).count("x = 1") == 600


def test_system_prompts_are_shown_once_and_variants_as_their_differences():
    b = _Book()
    prompt = "You are an agent.\n" + "\n".join(f"Rule {i}: be careful with item {i}." for i in range(120))
    first = b.add("system", prompt, to="agent-1")
    again = b.add("system", prompt, to="agent-1")
    other = b.add("system", prompt.replace("Rule 7:", "Rule 7 (u02):"), to="agent-2")
    changed = b.add("system", prompt.replace("Rule 9:", "Rule 9 CHANGED:"), to="agent-1")
    note = "[SYSTEM NOTIFICATION - NOT USER INPUT]\n" + "Boilerplate line.\n" * 25
    n1 = b.add("system", note + "<status>failed</status>", to="agent-1")
    n2 = b.add("system", note + "<status>completed</status>", to="agent-1")
    v = b.view()
    assert v[first].split("\n")[1] == "| [system prompt S1]" and len(v[first]) > len(prompt)
    assert v[again].endswith(f"| [system prompt S1, same as before ({first})]")
    # another agent's copy with one line changed: only that line, reversibly
    assert f"[system prompt S2: the same as {first} except these lines]" in v[other]
    assert "| @ instead of line 9:\n| + Rule 7 (u02): be careful with item 7." in v[other]
    assert len(v[other]) < 300
    assert _apply(prompt, _diff_lines(v[other])) == b.ledger.text(b.ledger.by_id()[other])
    # the same agent's system prompt changing is an anomaly: shown in full
    assert "[changed system prompt S3]" in v[changed] and "Rule 9 CHANGED" in v[changed] and len(v[changed]) > 2000
    # a notice like an earlier one: only what's new
    assert "S5: the same as" in v[n2] and "<status>completed</status>" in v[n2] and "Boilerplate" not in v[n2]
    assert "Boilerplate" in v[n1]


def _diff_lines(rendered: str) -> list[str]:
    body = [ln[2:] for ln in rendered.split("\n")[1:]]  # without the header and the "| " marks
    return body[1:]  # without the "[system prompt ...]" line


def _apply(earlier: str, diff: list[str]) -> str:
    """Rebuild a variant from the earlier text and its listed differences."""
    a = earlier.split("\n")
    out, i = [], 0
    k = 0
    while k < len(diff):
        m = re.match(r"@ (instead of|without) lines? (\d+)(?:-(\d+))?:?$|@ after line (\d+), added:$", diff[k])
        assert m, diff[k]
        if m.group(4) is not None:
            start, end = int(m.group(4)), int(m.group(4))
        else:
            start, end = int(m.group(2)) - 1, int(m.group(3) or m.group(2))
        out += a[i:start]
        i = end
        k += 1
        while k < len(diff) and diff[k].startswith("+ "):
            out.append(diff[k][2:])
            k += 1
    return "\n".join(out + a[i:])


def test_activity_notices_count_file_changes_and_keep_posts():
    b = _Book()
    lines = ["[activity on this host]", "u03 posted in #pln-5521: done at 673.5"]
    lines += [f"u03 changed files in /workspace: /workspace/PLN-5521/u03/best_{i}.csv" for i in range(300)]
    eid = b.add("prompt", "\n".join(lines), to="agent-2")
    v = b.view()[eid]
    assert "u03 posted in #pln-5521: done at 673.5" in v
    assert f"[300 file-change lines left out (u03: 300 file(s)); full text: fetch {eid}]" in v and len(v) < 400


@pytest.fixture(scope="module")
def real():
    log = next((REAL / "logs").glob("*.eval"))
    sample = read_eval_log(str(log), resolve_attachments=True).samples[0]
    inputs = extract_sample(sample)
    return inputs, build_material(sample, inputs, REAL)


def test_the_first_real_run_reads_smaller_and_every_entry_is_still_owned(real):
    inputs, m = real
    full = compact(m.ledger)  # without the run's policy: nothing is protected
    assert sum(len(c.text) for c in m.view) <= 105_000  # was 118,055 characters before this compaction
    owned = [eid for c in make_chunks(m.ledger, m.view) for eid in c.events]
    assert owned == [e.id for e in m.ledger.events]  # left-out entries still belong to a part (counted read)
    left_out = [c.id for c in m.view if not c.text]
    assert left_out and all(m.ledger.by_id()[i].kind == "attribution" for i in left_out)
    view_by_id = {c.id: c for c in m.view}
    for chunk in make_chunks(m.ledger, m.view):
        assert not any(f"[{i} " in render_chunk(chunk, view_by_id, 2) for i in left_out)
    # the status note's long write stays whole with the run's policy: it is a shared document
    status = next(e.id for e in m.ledger.events if e.kind == "tool_call" and "status.md <<" in m.ledger.text(e))
    assert "cut from the middle" not in view_by_id[status].text
    assert "cut from the middle" in next(c.text for c in full if c.id == status)
    assert policy_for(inputs, m.workspace).protected[0] == "/opt"


def test_the_resume_key_follows_what_the_parts_show(real):
    from swarmbench.judge.two_pass import progress_key

    _, m = real
    a = progress_key("d", "system", 60_000, m.view)
    b = progress_key("d", "system", 60_000, compact(m.ledger))  # another policy: other text in the parts
    assert a != b and a == progress_key("d", "system", 60_000, list(m.view))
