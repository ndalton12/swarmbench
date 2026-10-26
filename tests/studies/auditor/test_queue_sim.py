"""Tests for the proof-checker queue program (no model calls, no Lean)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from swarmbench.studies.auditor import queue_sim as q

# --- recognising checks ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd, expected",
    [
        ("lean-check /workspace/a.lean", ["lean-check"]),
        ("cp /opt/conference/problems/x.lean . && lean-check x.lean", ["lean-check"]),
        ("/opt/conference/bin/lean-check /workspace/notes/u05/t17.lean", ["lean-check"]),
        ("export PATH=/opt/conference/bin:$PATH\nsubmit sum_k sum_k.lean", ["submit"]),
        ("lean-check a.lean\nsubmit sum_k a.lean", ["lean-check", "submit"]),
        ("cat << 'EOF' > a.lean\ntheorem t : True := by\n  trivial\nEOF\nlean-check a.lean", ["lean-check"]),
        ("ps aux | grep lean-check", []),
        ("kill $(pgrep -f \"submit sum_k\")", []),
        ("submit_feedback --json", []),
        ("python3 submit.py", []),
        ("cat /opt/conference/bin/lean-check", []),
        ("timeout 100 lean-check a.lean", ["lean-check"]),
    ],
)
def test_checker_invocations(cmd, expected):
    assert q.checker_invocations(cmd) == expected


def test_command_text_unwraps_antigravity_and_json():
    ag = "toolAction: Checking\nCommandLine: lean-check /w/a.lean\nCwd: /workspace\nWaitMsBeforeAsync: 5000"
    assert q.command_text(ag) == "lean-check /w/a.lean"
    assert q.command_text(json.dumps({"CommandLine": "lean-check b.lean", "Cwd": "/"})) == "lean-check b.lean"
    assert q.is_checker_call(json.dumps({"command": "lean-check c.lean"}))
    assert q.checked_file("cd /w && lean-check /w/notes/u01/patch3.lean") == "patch3.lean"
    assert q.checked_file("submit sum_k_minus_one /home/u16/s.lean") == "s.lean"


def test_heredoc_body_is_not_searched():
    cmd = "cat <<EOF > f.lean\n-- run: lean-check other.lean\n; submit x y.lean\nEOF\necho done"
    assert q.checker_invocations(cmd) == []


@pytest.mark.parametrize(
    "out, status, expected",
    [
        ("Encountered error in step execution: Command timed out, needed to complete in 300s.", None, "timeout"),
        ("", "missing", "killed"),
        ("The command failed with exit code: 143\nOutput:\n", None, "killed"),
        ("lean-check: no such file: x.lean", None, "no_slot"),
        ("REJECTED: forbidden construct 'sorry' is not allowed in submissions.", None, "no_slot"),
        ("submit: problem 'x' is already solved and locked (credited to u03).", None, "no_slot"),
        ("a.lean:12:4: error: unsolved goals", None, "error"),
        ("REJECTED: the submission did not compile cleanly.", None, "error"),
        ("The command completed successfully.\nOutput:\n", None, "ok"),
        ("ACCEPTED: 'x' verified and credited to u01.", None, "ok"),
    ],
)
def test_classify_check(out, status, expected):
    assert q.classify_check(out, status) == expected


# --- slots ----------------------------------------------------------------------------------


def test_slot_formula_matches_known_runs():
    after = datetime(2026, 10, 21, 21, 35, tzinfo=UTC)
    # 30 agents, 36584 MiB: the 9-slot run
    assert q.slots_from_settings(36584, 30, 32, after)[0] == 9
    # 4 agents, 7984 MiB: one slot (confirmed by agents' listings)
    assert q.slots_from_settings(7984, 4, 6, after)[0] == 1
    # 30 agents, 63584 MiB: 36 by memory, capped at 32 processors
    slots, how = q.slots_from_settings(63584, 30, 32, after)
    assert slots == 32 and "capped" in how
    # before the 2026-10-16 change: one slot per 2 GiB
    before = datetime(2026, 10, 16, 20, 6, tzinfo=UTC)
    assert q.slots_from_settings(3224, 2, 6, before)[0] == 1
    # never fewer than one
    assert q.slots_from_settings(2000, 10, 6, after)[0] == 1


def test_run_slots_reads_compose(tmp_path):
    run = tmp_path / "2026-10-23T224732_proof-conference-planted-pool15"
    (run / "logs").mkdir(parents=True)
    (run / "logs" / "2026-10-23T22-47-40-00-00_swarm_x.eval").write_text("")
    homes = "\n".join(f"    - /home/u{i:02d}:exec,mode=0755,uid={2000 + i},gid={2000 + i},size=1g" for i in range(1, 11))
    (run / "compose.yaml").write_text(
        f"services:\n  team-swarm:\n    tmpfs:\n    - /tmp:exec\n{homes}\n    mem_limit: 23584m\n    cpus: 32.0\n"
    )
    info = q.run_slots(run)
    assert info.slots == 12


# --- the simulation -------------------------------------------------------------------------


def test_one_slot_serves_in_turn_with_one_second_polling():
    jobs = [q.SimJob("a", 0.0, 10.0), q.SimJob("b", 1.0, 10.0), q.SimJob("c", 2.0, 10.0)]
    sim = q.simulate(jobs, slots=1, poll=1.0)
    a, b, c = (sim.results[k] for k in "abc")
    assert a.acquire == 0.0 and a.end == 10.0
    # b and c both scan at whole seconds; b arrived first and scans at 10.0 (1 + 9 s), c at 10.0 too:
    # first in arrival order wins
    assert b.acquire == pytest.approx(10.0)
    assert b.end == pytest.approx(20.0)
    assert c.acquire == pytest.approx(20.0)
    assert sim.waiting_at(5.0) == 2
    assert sim.waiting_at(15.0) == 1


def test_waiter_takes_slot_at_its_next_scan_not_at_release():
    jobs = [q.SimJob("a", 0.0, 10.5), q.SimJob("b", 1.0, 5.0)]
    sim = q.simulate(jobs, slots=1, poll=1.0)
    # released at 10.5; b scans at 1, 2, ... so it gets the slot at 11.0
    assert sim.results["b"].acquire == pytest.approx(11.0)
    assert sim.results["b"].wait == pytest.approx(10.0)


def test_new_arrival_can_overtake_a_waiter():
    jobs = [q.SimJob("a", 0.0, 10.2), q.SimJob("b", 1.0, 5.0), q.SimJob("c", 10.5, 5.0)]
    sim = q.simulate(jobs, slots=1, poll=1.0)
    # slot frees at 10.2; c arrives at 10.5 and scans at once, before b's scan at 11.0
    assert sim.results["c"].acquire == pytest.approx(10.5)
    assert sim.results["b"].acquire == pytest.approx(15.5) or sim.results["b"].acquire == pytest.approx(16.0)


def test_time_limit_counts_waiting_and_frees_the_slot():
    jobs = [q.SimJob("a", 0.0, 1000.0), q.SimJob("b", 10.0, 5.0)]
    sim = q.simulate(jobs, slots=1, poll=1.0)
    a, b = sim.results["a"], sim.results["b"]
    assert a.outcome == "timeout" and a.end == pytest.approx(300.0)
    assert b.acquire == pytest.approx(300.0)
    assert b.outcome == "done" and b.end == pytest.approx(305.0)
    # b's own limit (310) counts its waiting too: 20 s of checking no longer fits
    sim = q.simulate([q.SimJob("a", 0.0, 1000.0), q.SimJob("b", 10.0, 20.0)], slots=1, poll=1.0)
    assert sim.results["b"].outcome == "timeout" and sim.results["b"].end == pytest.approx(310.0)
    jobs = [q.SimJob("a", 0.0, 1000.0), q.SimJob("b", 10.0, 20.0), q.SimJob("c", 11.0, 20.0)]
    sim = q.simulate(jobs, slots=1, poll=1.0)
    # b times out at 310 after taking the slot at 300; c gets it at 310 and times out at 311
    assert sim.results["c"].outcome == "timeout" and sim.results["c"].end == pytest.approx(311.0)
    # a waiter can time out without ever getting a slot: here c arrives just as a frees the slot,
    # takes it before b's next scan and holds it past b's limit
    jobs = [q.SimJob("a", 0.0, 99.5), q.SimJob("b", 10.0, 50.0), q.SimJob("c", 99.7, 1000.0)]
    sim = q.simulate(jobs, slots=1, poll=1.0)
    assert sim.results["c"].acquire == pytest.approx(99.7)
    assert sim.results["b"].acquire is None and sim.results["b"].outcome == "timeout"
    assert sim.results["b"].end == pytest.approx(310.0)


def test_outside_departure_frees_slot():
    jobs = [q.SimJob("a", 0.0, 100.0, leave_at=5.0), q.SimJob("b", 1.0, 10.0)]
    sim = q.simulate(jobs, slots=1, poll=1.0)
    assert sim.results["a"].outcome == "left"
    assert sim.results["b"].acquire == pytest.approx(5.0)


def test_no_slot_checks_never_wait():
    jobs = [q.SimJob("a", 0.0, 100.0), q.SimJob("b", 1.0, 0.3, uses_slot=False)]
    sim = q.simulate(jobs, slots=1, poll=1.0)
    assert sim.results["b"].total == pytest.approx(0.3)


def test_many_slots_no_waiting():
    jobs = [q.SimJob(str(i), float(i), 30.0) for i in range(5)]
    sim = q.simulate(jobs, slots=5)
    assert all(r.wait == 0 for r in sim.results.values())


# --- checks from the commands table, estimates, validation, forecasts -------------------------


def _row(key, agent, t, dur, out="The command completed successfully.\nOutput:\n", cmd=None, status="complete"):
    return {
        "key": key,
        "agent": agent,
        "command": cmd or f"lean-check /w/{key}.lean",
        "t_call": datetime.fromtimestamp(t, UTC),
        "duration_s": dur,
        "t_result": None,
        "output": out,
        "output_status": status,
    }


def test_checks_from_rows_and_estimates():
    rows = [
        _row("a1", "a", 0, 20, cmd="lean-check /w/f.lean"),
        _row("b1", "b", 1, 35, cmd="lean-check /w/g.lean"),  # waited for a1 (1 slot)
        _row("a2", "a", 100, 22, out="f.lean:3:1: error: x", cmd="lean-check /w/f.lean"),
        _row("c1", "c", 5, None, out="", status="missing", cmd="lean-check /w/h.lean"),
        _row("x", "a", 7, 3, cmd="ls /w"),
    ]
    checks = q.checks_from_rows(rows)
    assert [c.key for c in checks] == ["a1", "b1", "c1", "a2"]
    est = {c.key: c for c in q.estimate_checking_times(checks, slots=1)}
    assert est["a1"].checking_source == "own (no wait)" and est["a1"].checking_s == 20
    # b1 started while a1 held the only slot: its own duration is not used
    assert est["b1"].checking_source != "own (no wait)"
    assert est["c1"].outcome == "killed"


def test_validate_run_reproduces_a_simple_line():
    # three checks of 10 s each at t=0,1,2 with one slot; the first is clean, the others are busy
    rows = [
        _row("a", "a", 0.0, 10.0, cmd="lean-check /w/f.lean"),
        _row("b", "b", 1.0, 19.0, cmd="lean-check /w/f.lean"),
        _row("c", "c", 2.0, 28.0, cmd="lean-check /w/f.lean"),
    ]
    checks = q.checks_from_rows(rows)
    out = {r["key"]: r for r in q.validate_run(checks, slots=1, seed=None)}
    assert not out["a"]["busy_at_start"] and out["b"]["busy_at_start"]
    assert out["a"]["sim_total_s"] == pytest.approx(10.0)
    # b and c both wait for a; which of them scans first after a ends is down to their scan phase
    second, third = sorted([out["b"]["sim_total_s"], out["c"]["sim_total_s"]])
    assert second == pytest.approx(18.5, abs=1.5)
    assert third == pytest.approx(28.0, abs=2.5)


def test_times_off():
    assert q.times_off(20, 10) == pytest.approx(2.0)
    assert q.times_off(5, 10) == pytest.approx(2.0)
    assert q.times_off(0.2, 0.9) == pytest.approx(1.0)
    assert q.times_off(None, 3) is None


def _busy_run():
    # 1 slot; each of 3 agents sends a 60 s check every 70 s for 30 minutes: a growing line
    rows = []
    for agent in "abc":
        for i in range(26):
            t = i * 70.0 + "abc".index(agent)
            rows.append(_row(f"{agent}{i}", agent, t, None, cmd=f"lean-check /w/{agent}.lean"))
    jobs = [
        q.SimJob(r["key"], r["t_call"].timestamp(), 60.0) for r in rows
    ]
    sim = q.simulate(jobs, slots=1)
    for r in rows:
        s = sim.results[r["key"]]
        if s.outcome == "timeout":
            r["output"] = "Command timed out, needed to complete in 300s"
            r["duration_s"] = 300.0
        else:
            r["duration_s"] = s.total
    return q.checks_from_rows(rows)


def test_queue_truth_and_forecast_on_a_busy_line():
    checks = _busy_run()
    truth = q.truth_from_checks(checks, slots=1, t_freeze=600.0, run_end=2000.0)
    assert truth["slots"] == 1
    assert truth["real_waiting_5min"] >= 1
    assert truth["real_hits_limit"] is True
    fc = q.forecast_from_checks(checks, slots=1, t_freeze=600.0, run_end=2000.0, reps=30)
    assert set(fc) >= {"sim_typical_wait_s", "sim_waiting_5min", "sim_waiting_10min", "sim_hits_limit"}
    assert fc["sim_waiting_5min"] >= 1
    assert fc["sim_typical_wait_s"] > 60
    state = q.state_from_checks(checks, 1, 600.0, 2000.0)
    assert state["waiting"] == state["in_flight"] - 1


def test_forecast_quiet_queue():
    rows = [_row(f"a{i}", "a", i * 200.0, 15.0, cmd="lean-check /w/f.lean") for i in range(6)]
    checks = q.checks_from_rows(rows)
    fc = q.forecast_from_checks(checks, slots=4, t_freeze=700.0, reps=20)
    assert fc["sim_waiting_5min"] == 0 and fc["sim_hits_limit"] is False
    assert fc["sim_typical_wait_s"] == pytest.approx(15.0)
    truth = q.truth_from_checks(checks, slots=4, t_freeze=700.0)
    assert truth["real_waiting_10min"] == 0 and truth["real_typical_wait_s"] == pytest.approx(15.0)


# --- process records ------------------------------------------------------------------------


def _dump(rows):
    data = "".join(json.dumps(r) + "\n" for r in rows)
    return json.dumps({"files": {"procs.jsonl": {"size": len(data), "data": data, "next": len(data)}}, "alive": True})


def test_parse_proc_dump_whole_and_cut():
    rows = [{"pid": i, "ppid": 1, "uid": 2001, "cmd": f"/bin/sh lean-check /w/f{i}.lean", "t": 100.0 + i} for i in range(5)]
    assert q.parse_proc_dump(_dump(rows)) == rows
    out = _dump(rows)
    cut = out.index('\\"pid\\": 3') + 5  # Inspect cut the output inside the fourth row
    assert q.parse_proc_dump(out[:cut]) == rows[:3]
    assert q.parse_proc_dump("not a dump") == []


def _procs_for_one_check(t0=1000.0, wait=40.0):
    return [
        {"pid": 50, "ppid": 10, "uid": 2003, "cmd": "/bin/sh /usr/local/bin/lean-check /w/a.lean", "t": t0 + 0.2},
        {"pid": 51, "ppid": 50, "uid": 2003, "cmd": "/bin/sh /usr/local/bin/lean-check /w/a.lean", "t": t0 + 1.2},
        {"pid": 90, "ppid": 50, "uid": 2003, "cmd": "lake env lean -DautoImplicit=false /w/a.lean", "t": t0 + wait},
        {"pid": 91, "ppid": 90, "uid": 2003, "cmd": "lean -DautoImplicit=false /w/a.lean", "t": t0 + wait + 2},
        # an agent compiling directly, outside the slots
        {"pid": 70, "ppid": 11, "uid": 2003, "cmd": "bash -c lake env lean /w/a.lean", "t": t0 + 5},
        {"pid": 71, "ppid": 70, "uid": 2003, "cmd": "lake env lean /w/a.lean", "t": t0 + 5.1},
    ]


def test_slot_times_and_attach():
    starts, acqs = q.slot_times(_procs_for_one_check())
    assert [s["pid"] for s in starts if not s["parent_is_checker"]] == [50]
    assert [(a["t"], a["parent"]) for a in acqs] == [(1040.0, 50)]
    rows = [_row("k", "agent-3", 1000.0, 45.0, cmd="lean-check /w/a.lean")]
    (c,) = q.attach_slot_times(q.checks_from_rows(rows), _procs_for_one_check())
    assert c.lc_start == pytest.approx(1000.2) and c.acquire == pytest.approx(1040.0)
    assert c.real_wait == pytest.approx(39.8)
    est = q.estimate_checking_times([c], slots=1)
    assert est[0].checking_source == "measured" and est[0].checking_s == pytest.approx(5.0)


def test_attach_when_the_parent_record_was_lost():
    # the lean-check's own row was cut; its lock subshell (seen late) and its compiler are known
    procs = [dict(p) for p in _procs_for_one_check() if p["pid"] != 50]
    procs[0]["t"] = 1030.0
    rows = [_row("k", "agent-3", 1000.0, 45.0, cmd="lean-check /w/a.lean")]
    (c,) = q.attach_slot_times(q.checks_from_rows(rows), procs)
    assert c.lc_start is None and c.acquire == pytest.approx(1040.0)
    assert c.real_wait == pytest.approx(40.0)


def test_agent_uid():
    assert q.agent_uid("agent-14") == 2014
    assert q.agent_uid("x") is None


# --- repeatability and what is knowable at the freeze ---------------------------------------

_FORECAST_SCRIPT = """
import json
from tests.studies.auditor.test_queue_sim import _busy_run
from swarmbench.studies.auditor import queue_sim as q
checks = _busy_run()
print(json.dumps([q.forecast_from_checks(checks, 2, t, run_end=2000.0, reps=15, seed=3) for t in (400.0, 800.0)]))
"""


def test_forecast_is_repeatable_across_processes():
    # string hashing (and so set order) differs between processes; the forecast must not
    outs = []
    for hashseed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hashseed}
        r = subprocess.run([sys.executable, "-c", _FORECAST_SCRIPT], capture_output=True, text=True, env=env, check=True)
        outs.append(r.stdout)
    assert outs[0] == outs[1]
    checks = _busy_run()
    a = q.forecast_from_checks(checks, 2, 800.0, run_end=2000.0, reps=15, seed=3)
    assert a == q.forecast_from_checks(checks, 2, 800.0, run_end=2000.0, reps=15, seed=3)


def test_simultaneous_waiters_are_served_in_key_order_whatever_the_input_order():
    jobs = [q.SimJob(k, 1.0, 5.0) for k in "dbca"] + [q.SimJob("x", 0.0, 10.0)]
    a = q.simulate(jobs, slots=1, poll=1.0)
    b = q.simulate(list(reversed(jobs)), slots=1, poll=1.0)
    order = sorted("abcd", key=lambda k: a.results[k].acquire)
    assert order == list("abcd")
    assert {k: r.acquire for k, r in a.results.items()} == {k: r.acquire for k, r in b.results.items()}


def test_state_uses_only_what_was_knowable():
    rows = [
        _row("busy", "a", 0.0, 100.0, cmd="lean-check /w/f.lean"),
        # in flight at t=50; that it will turn out not to need a slot is not known yet
        _row("late", "b", 40.0, 30.0, out="REJECTED: forbidden construct 'sorry'", cmd="submit p /w/g.lean"),
        _row("done", "c", 10.0, 5.0, cmd="lean-check /w/h.lean"),
    ]
    checks = q.checks_from_rows(rows)
    state = q.state_from_checks(checks, slots=1, t_freeze=50.0)
    assert [c["key"] for c in state["checks"]] == ["busy", "late"]
    assert state["in_flight"] == 2 and state["waiting"] == 1
    # the future outcome must not change the state
    alt = [q.replace(c, outcome="ok") if c.key == "late" else c for c in checks]
    assert q.state_from_checks(alt, slots=1, t_freeze=50.0) == state
