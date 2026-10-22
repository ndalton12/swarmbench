"""Required checks on very large runs: repeated monitor flags are one check, the harness's own
plumbing is not a check, and critical flags keep their own numbered check."""

from __future__ import annotations

from types import SimpleNamespace

from swarmbench.judge.digest import BATCH_CHARS, _batches, _line
from swarmbench.judge.reconcile import CRITICAL_MARK, monitor_check_ids, obligations
from swarmbench.judge.review import Note

PLUMBING = ("/usr/bin/timeout -k 5s 16s curl -s --max-time 15.000 -H Content-Type: application/json -H Accept: "
            "application/json, text/event-stream -X POST --data-binary @- http://localhost:3024/mcp/messages")


def _flag(agent, summary, evidence, severity="medium", **kw):
    return {"agent": agent, "severity": severity, "category": "network", "summary": summary, "evidence": evidence,
            **kw}


def _checks(flags):
    inputs = SimpleNamespace(monitor_flags=flags, bridge_uses=[], protected_hashes={})
    return obligations(SimpleNamespace(events=[]), inputs, SimpleNamespace(files=[]), []), inputs


def test_repeats_are_grouped_plumbing_left_out_and_critical_flags_numbered_first():
    flags = [_flag("agent-1", "proposed: referring to an external URL", "https://www.apache.org/licenses/LICENSE-2.0")
             for _ in range(40)]  # fmt: skip
    flags.insert(5, _flag(None, "ran: fetching a URL over the network", PLUMBING, severity="high"))
    flags.insert(7, _flag("agent-2", "ran: mounting a filesystem", "mount", severity="critical", category="escape"))
    flags.append(_flag("agent-3", "proposed: referring to an external URL", "https://www.apache.org/licenses/LICENSE-2.0"))
    checks, inputs = _checks(flags)
    assert len(checks) == 3
    assert checks[0].startswith(CRITICAL_MARK) and "agent-2" in checks[0]
    assert "on agent-1" in checks[1] and "and 39 more like it" in checks[1]
    assert "on agent-3" in checks[2] and "more like it" not in checks[2]
    assert not any("localhost:3024" in c for c in checks)
    assert monitor_check_ids(inputs) == {"C1": flags[7]}


def test_a_critical_flag_is_never_grouped_or_dropped():
    crit = [_flag(None, "ran: fetching a URL over the network", PLUMBING, severity="critical") for _ in range(2)]
    checks, inputs = _checks(crit)
    assert len(checks) == 2 and all(c.startswith(CRITICAL_MARK) for c in checks)
    assert list(monitor_check_ids(inputs)) == ["C1", "C2"]


def test_batches_are_even_with_no_small_leftover():
    notes = [Note(type="observation", text="x" * 1000, sources=["L0001"], chunk="C1") for _ in range(250)]
    sizes = [sum(len(_line(n)) for n in b) for b in _batches(notes)]
    assert len(sizes) == 3 and max(sizes) <= BATCH_CHARS and min(sizes) > 0.8 * max(sizes)
