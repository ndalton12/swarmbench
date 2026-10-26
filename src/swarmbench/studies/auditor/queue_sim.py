"""The proof-checker queue program: a small simulation of the proof conference's checker.

This is one of the free yardsticks of the auditor prediction study
(docs/research/auditor-prediction-plan.md, "The yardsticks" and "A closer look at waiting lines").
It answers two questions without any model calls:

- Driven by each real check's start time and its checking time, how long does the program say each
  check waited, and how close is that to reality?  (``validate_run``)
- At a frozen moment of a real run, what does the program forecast for the next 10 minutes?
  (``queue_forecast``; the real values are ``queue_truth``)

The checker's real rules
------------------------
Read from ``scenarios/proof_conference/protected/conference/bin/`` and the run records:

1. **What a check is.** An agent runs ``lean-check FILE`` (or ``submit PROBLEM FILE``, which runs
   ``lean-check`` on a private copy after two quick text checks). ``lean-check`` first runs a small
   Python note (``_locked.py``, a fraction of a second), then needs a **slot** to compile.
   ``submit`` can reject a file before compiling (forbidden word, template mismatch, problem already
   solved, unknown problem); such a check never takes a slot. ``lean-check`` on a missing file
   exits at once, also without a slot.
2. **Slots.** The slots are lock files ``/tmp/.lean-check/slot1 .. slotN``, each held with
   ``flock`` for the whole compile. N is ``LEAN_CHECK_SLOTS`` if set (no run set it); otherwise
   ``(memory limit in MiB - 2560 - 1024 - 768 x number of /home/uNN folders) // 1024``, at least 1
   and at most ``nproc``. Runs started before 2026-10-16 20:22 UTC used the older rule
   ``memory limit // 2 GiB``. Event users (the planted-proof "peer") have no ``/home`` folder, so
   they don't count. ``run_slots`` gives each run's N and how it was found.
3. **Waiting.** A check scans slot1..slotN in order and takes the first free one. If none is free
   it sleeps 1 second and scans again, forever. There is no queue order: when a slot frees, the
   first waiting check (or newly arriving check) whose next scan comes after that moment wins.
   A new check scans immediately on arrival, so it can overtake checks that have waited longer.
4. **The time limit.** Lean-check itself has no time limit. The limit is the agent harness's:
   Antigravity's ``run_command`` stops any command after **300 seconds** in total (waiting plus
   compiling) and reports "Command timed out, needed to complete in 300s". The whole process tree
   is killed, which releases a held slot: ``ps`` listings taken by agents never show a
   ``lean-check`` process older than 5 minutes. (``submit``'s own 10-minute compile limit is
   therefore never reached.)
5. **Outside the rules.** Agents can kill each other's checks (``kill``/``pkill``), which frees a
   slot early, and can run ``lake env lean`` directly, which compiles without a slot (uses
   processors but never waits). Lock files an agent can't read are skipped; if none is readable
   the check compiles without waiting. The program models 1-4; kills enter only as real departure
   times in the driven validation, and direct compiles are left out of the queue.

The checking time
-----------------
The logs record when each check started and when its result came back, but not when it got a
slot, so the checking time (compile time) of a check that waited is not measured. It is estimated
(``estimate_checking_times``) without using that check's own end time:

- A check that started while fewer than N other slot-using checks were in flight cannot have
  waited, so its checking time is its measured duration ("no wait").
- Any other check borrows the checking time of no-wait checks: the same agent's nearest no-wait
  check of the same file with the same kind of result (Lean errors or none), else the median for
  the same file name in the run, else the run median for that kind of result, else the run median,
  else ``DEFAULT_CHECKING_S``.

Re-running the real proof files through the real checker offline would measure checking times
directly; that needs the Lean image and is not done here.

Times are seconds since the Unix epoch (floats) throughout.
"""

from __future__ import annotations

import heapq
import json
import math
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

LIMIT_S = 300.0
"""Antigravity's limit on one command's total time (waiting plus compiling)."""
POLL_S = 1.0
"""A waiting check sleeps this long between scans of the slots."""
SCAN_OVERHEAD_S = 0.02
"""Extra time one scan takes (forks a subshell per slot), so a waiter's period is a bit over 1 s."""
DEFAULT_CHECKING_S = 30.0
"""Checking time used when a run has no no-wait check to learn from."""
HORIZON_S = 600.0
LEARNED = ("measured", "own (no wait)")
"""Checking-time sources that come from the check itself (not borrowed from other checks)."""
"""The frozen-moment forecasts look 10 minutes ahead."""

# Runs started before this used lean-check's first slot rule (one slot per 2 GiB of memory).
_NEW_SLOT_RULE_FROM = datetime(2026, 10, 16, 20, 22, tzinfo=UTC)

# Slot counts confirmed from the run records (lock file names in agents' listings).
SLOT_EVIDENCE: dict[str, str] = {
    "2026-10-16T140306_proof-conference": "agents' listings show only /tmp/.lean-check/slot1",
    "2026-10-19T162241_proof-conference": "agents' listings show only /tmp/.lean-check/slot1",
    "2026-10-20T121334_proof-conference": "agents' listings show only slot1; an agent complained "
    "about 'the single /tmp/.lean-check/slot1 lock'",
}


# --- recognising checks ---------------------------------------------------------------------

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?:\n|$)", re.DOTALL)
# a checker program in command position: at the start, after a separator, or after a wrapper
_INVOCATION = re.compile(
    r"(?:^|[;&|(`]|\$\(|\n|\bthen\b|\bdo\b|\belse\b|\btimeout\s+\S+|\bnohup\b|\btime\b|\bexec\b)"
    r"\s*(?:\S*/)?(lean-check|submit)(?=\s+[^\s|;&<>])"
)
_DIRECT_LEAN = re.compile(r"\blake\s+env\s+lean\b|(?:^|[;&|\n]\s*)(?:\S*/)?lean\s+-")


def command_text(command: str | None) -> str:
    """The shell text of a command: Antigravity's ``CommandLine`` or a ``command``/``cmd``
    argument when the command column holds JSON arguments, else the text itself."""
    if not isinstance(command, str) or not command:
        return ""
    s = command.strip()
    if s.startswith("{"):
        try:
            args = json.loads(s)
        except ValueError:
            return s
        if isinstance(args, dict):
            for k in ("CommandLine", "command", "cmd"):
                v = args.get(k)
                if isinstance(v, str):
                    return v
                if isinstance(v, list):
                    return " ".join(map(str, v))
    m = re.search(r"CommandLine: (.*?)(?:\n(?:Cwd|WaitMsBeforeAsync|toolAction|toolSummary):|\Z)", s, re.DOTALL)
    return m.group(1) if m else s


def strip_heredocs(text: str) -> str:
    """Drop here-document bodies (file contents written inline), keeping the command lines."""
    return _HEREDOC.sub("\n", text)


def checker_invocations(command: str | None) -> list[str]:
    """The checker programs a command runs, in order (``lean-check`` / ``submit``)."""
    return _INVOCATION.findall(strip_heredocs(command_text(command)))


def is_checker_call(command: str | None) -> bool:
    """Does this command run the proof checker (``lean-check`` or ``submit``)?"""
    return bool(checker_invocations(command))


def compiles_directly(command: str | None) -> bool:
    """Does it run Lean directly (``lake env lean``), compiling without a slot?"""
    return bool(_DIRECT_LEAN.search(strip_heredocs(command_text(command))))


_TIMEOUT = re.compile(r"needed to complete in \d+s|command timed out", re.IGNORECASE)
_NO_SLOT = re.compile(
    r"lean-check: no such file|usage: lean-check|REJECTED: forbidden construct|REJECTED: code outside"
    r"|REJECTED: wrong number of editable|REJECTED: this problem needs an answer|REJECTED: cannot read"
    r"|REJECTED: nested|REJECTED: unclosed|REJECTED: '-- EDITABLE END'|already solved and locked"
    r"|submit: no such problem|submit: cannot read"
)
_KILLED = re.compile(r"exit code: (?:-9|-15|137|143)\b|\bKilled\b|\bTerminated\b|signal: killed", re.IGNORECASE)
_LEAN_ERROR = re.compile(r":\d+:\d+: error|^error:|REJECTED: the submission did not compile", re.MULTILINE)


def classify_check(output: str | None, output_status: str | None = None) -> str:
    """What happened to a check, from its real output.

    ``timeout`` (stopped at the 300 s limit), ``no_slot`` (finished without compiling),
    ``killed`` (stopped by a signal or never returned), ``error`` (compiled, Lean reported errors),
    ``ok`` (compiled without errors).
    """
    text = output if isinstance(output, str) else ""
    if _TIMEOUT.search(text):
        return "timeout"
    if output_status == "missing" or not text.strip():
        return "killed"
    if _KILLED.search(text):
        return "killed"
    if _NO_SLOT.search(text):
        return "no_slot"
    if _LEAN_ERROR.search(text):
        return "error"
    return "ok"


def checked_file(command: str | None) -> str | None:
    """The file name a check compiles (basename), for matching repeated checks of one file."""
    text = strip_heredocs(command_text(command))
    m = re.search(r"(?:lean-check|submit\s+\S+)\s+(\S+\.lean)", text)
    return m.group(1).rsplit("/", 1)[-1].strip("'\"") if m else None


# --- slots ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotInfo:
    slots: int
    how: str
    """How the count was found: the formula's inputs, and any confirmation from the records."""


def slots_from_settings(
    mem_limit_mib: int, homes: int, nproc: int, started: datetime | None = None
) -> tuple[int, str]:
    """lean-check's default slot count for a container (see rule 2 in the module docstring)."""
    if started is not None and started < _NEW_SLOT_RULE_FROM:
        slots = mem_limit_mib // 2048
        how = f"old rule: {mem_limit_mib} MiB // 2048"
    else:
        mb = mem_limit_mib - 2560 - 1024 - homes * 768
        slots = mb // 1024
        how = f"({mem_limit_mib} - 2560 - 1024 - {homes} x 768) // 1024 = {slots}"
    if slots > nproc:
        how += f", capped at {nproc} processors"
    slots = max(1, min(slots, nproc))
    return slots, how


def _run_started(run_dir: Path) -> datetime | None:
    m = re.match(r"(\d{4}-\d\d-\d\d)T(\d\d)(\d\d)(\d\d)", run_dir.name)
    if not m:
        return None
    # run folder names are local (Pacific) time; the logs know the exact UTC start
    for log in sorted((run_dir / "logs").glob("*.eval")):
        m2 = re.match(r"(\d{4}-\d\d-\d\d)T(\d\d)-(\d\d)-(\d\d)", log.name)
        if m2:
            return datetime.fromisoformat(f"{m2[1]}T{m2[2]}:{m2[3]}:{m2[4]}+00:00")
    return None


def run_slots(run_dir: Path | str) -> SlotInfo:
    """A proof-conference run's slot count, from its ``compose.yaml`` (memory limit, ``/home``
    folders, processors), confirmed against ``SLOT_EVIDENCE`` where the records show it."""
    run_dir = Path(run_dir)
    text = (run_dir / "compose.yaml").read_text()
    if m := re.search(r"LEAN_CHECK_SLOTS\D+(\d+)", text):
        return SlotInfo(int(m[1]), "LEAN_CHECK_SLOTS set in compose.yaml")
    mem = re.search(r"mem_limit:\s*(\d+)m", text)
    cpus = re.search(r"\bcpus:\s*([\d.]+)", text)
    if not mem:
        raise ValueError(f"{run_dir}: no mem_limit in compose.yaml")
    homes = len(re.findall(r"^\s*-\s*/home/u\d+:", text, re.MULTILINE))
    # compose's cpus is the scenario's request capped at the machine's processors; every proof
    # run asked for more than its machine had, so it equals what nproc saw
    nproc = int(float(cpus[1])) if cpus else 1
    slots, how = slots_from_settings(int(mem[1]), homes, nproc, _run_started(run_dir))
    if run_dir.name in SLOT_EVIDENCE:
        how += f"; confirmed: {SLOT_EVIDENCE[run_dir.name]}"
    return SlotInfo(slots, how)


# --- checks ---------------------------------------------------------------------------------


@dataclass
class Check:
    key: str
    agent: str
    start: float
    end: float | None
    """When it really ended (result, time-out or kill); None if never known."""
    outcome: str
    """See ``classify_check``."""
    file: str | None = None
    n_invocations: int = 1
    checking_s: float | None = None
    """Checking (compile) time, measured or estimated; see ``estimate_checking_times``."""
    checking_source: str = ""
    lc_start: float | None = None
    """When the ``lean-check`` process started, from the process records (None if not seen)."""
    acquire: float | None = None
    """When it got a slot (its compiler started), from the process records (None if not seen)."""

    @property
    def arrive(self) -> float:
        """When it joined the line: the ``lean-check`` start if seen, else the call time."""
        return self.lc_start if self.lc_start is not None else self.start

    @property
    def real_wait(self) -> float | None:
        """Measured time in line (None unless the process records show when it got a slot)."""
        return None if self.acquire is None else max(0.0, self.acquire - self.arrive)

    @property
    def uses_slot(self) -> bool:
        return self.outcome != "no_slot"

    @property
    def real_total(self) -> float | None:
        """The real time from issuing the check to its result (``LIMIT_S`` for a time-out)."""
        if self.outcome == "timeout":
            return LIMIT_S
        if self.outcome in ("error", "ok", "no_slot") and self.end is not None:
            return self.end - self.start
        return None

    def real_end(self, run_end: float | None = None) -> float:
        """When it left the system in reality (for in-flight counts)."""
        if self.outcome == "timeout":
            return self.start + LIMIT_S
        if self.end is not None:
            return min(self.end, self.start + LIMIT_S)
        cap = self.start + LIMIT_S
        return min(cap, run_end) if run_end is not None else cap


def ended_by(c: Check, t: float, run_end: float | None = None) -> bool:
    """Had this check visibly ended by time t (its result back, or its 300 s up)? Knowable at t."""
    if c.end is not None and c.end <= t:
        return True
    if c.start + LIMIT_S <= t:
        return True
    return run_end is not None and c.end is None and run_end <= t


def _ts(x: Any) -> float | None:
    if x is None:
        return None
    try:
        if isinstance(x, float) and math.isnan(x):
            return None
    except TypeError:
        pass
    if isinstance(x, (int, float)):
        return float(x)
    if hasattr(x, "timestamp"):
        try:
            v = x.timestamp()
        except (ValueError, TypeError):  # NaT
            return None
        return None if math.isnan(v) else float(v)
    return datetime.fromisoformat(str(x)).timestamp()


def checks_from_rows(rows: Iterable[dict[str, Any]]) -> list[Check]:
    """Checks from rows of the commands table (one run): rows whose command runs the checker.

    The end time is ``t_call + duration_s`` (for Antigravity background tasks, when the task
    finished), else ``t_result``.
    """
    out = []
    for r in rows:
        inv = checker_invocations(r.get("command"))
        if not inv:
            continue
        start = _ts(r.get("t_call"))
        if start is None:
            continue
        dur = r.get("duration_s")
        end = None
        if dur is not None and not (isinstance(dur, float) and math.isnan(dur)):
            end = start + float(dur)
        elif (tr := _ts(r.get("t_result"))) is not None:
            end = tr
        status = r.get("output_status")
        outcome = classify_check(r.get("output"), status if isinstance(status, str) else None)
        if outcome == "killed" and end is not None and end - start >= LIMIT_S - 1:
            outcome = "timeout"
        out.append(
            Check(
                key=str(r.get("key")),
                agent=str(r.get("agent")),
                start=start,
                end=end,
                outcome=outcome,
                file=checked_file(r.get("command")),
                n_invocations=len(inv),
            )
        )
    out.sort(key=lambda c: c.start)
    return out


def in_flight(checks: list[Check], t: float, run_end: float | None = None, exclude: str | None = None) -> int:
    """Slot-using checks in flight at time t (started at or before t, not yet ended), by the
    real record."""
    return sum(
        1
        for c in checks
        if c.uses_slot and c.key != exclude and c.start <= t < c.real_end(run_end)
    )


def _median(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def estimate_checking_times(
    checks: list[Check], slots: int, cutoff: float | None = None, run_end: float | None = None
) -> list[Check]:
    """Each check with ``checking_s`` filled in (see "The checking time" in the module docstring).

    With ``cutoff``, only checks that ended by then are learned from, so a forecast made at that
    moment uses nothing from its future.
    """
    starts = np.array([c.start for c in checks if c.uses_slot])
    ends = np.array([c.real_end(run_end) for c in checks if c.uses_slot])
    clean: list[Check] = []
    out: list[Check] = []
    for c in checks:
        c = replace(c)
        if not c.uses_slot:
            c.checking_s = c.real_total if c.real_total is not None else 1.0
            c.checking_source = "no slot"
        elif (
            c.acquire is not None
            and c.outcome in ("error", "ok")
            and c.end is not None
            and (cutoff is None or c.end <= cutoff)
        ):
            c.checking_s = max(0.0, c.end - c.acquire)
            c.checking_source = "measured"
            clean.append(c)
        elif c.outcome in ("error", "ok") and c.end is not None:
            others = int(np.sum((starts <= c.start) & (ends > c.start))) - 1  # minus itself
            if others < slots and (cutoff is None or c.end <= cutoff):
                c.checking_s = c.end - c.arrive
                c.checking_source = "own (no wait)"
                clean.append(c)
        out.append(c)

    by_agent_file: dict[tuple, list[Check]] = defaultdict(list)
    by_file: dict[tuple, list[float]] = defaultdict(list)
    by_file_any: dict[str | None, list[float]] = defaultdict(list)
    by_kind: dict[str, list[float]] = defaultdict(list)
    for c in clean:
        by_agent_file[(c.agent, c.file, c.outcome)].append(c)
        by_agent_file[(c.agent, c.file, None)].append(c)
        by_file[(c.file, c.outcome)].append(c.checking_s)
        by_file_any[c.file].append(c.checking_s)
        by_kind[c.outcome].append(c.checking_s)
    run_all = [c.checking_s for c in clean]

    for c in out:
        if c.checking_s is not None:
            continue
        kind = c.outcome if c.outcome in ("error", "ok") else None
        near = by_agent_file.get((c.agent, c.file, kind)) if c.file else None
        if near:
            best = min(near, key=lambda o: abs(o.start - c.start))
            c.checking_s, c.checking_source = best.checking_s, "same agent and file"
            continue
        if c.file and (v := _median(by_file.get((c.file, kind), []) if kind else by_file_any.get(c.file, []))):
            c.checking_s, c.checking_source = v, "same file name"
            continue
        if kind and (v := _median(by_kind.get(kind, []))):
            c.checking_s, c.checking_source = v, f"run median ({kind})"
            continue
        if v := _median(run_all):
            c.checking_s, c.checking_source = v, "run median"
            continue
        c.checking_s, c.checking_source = DEFAULT_CHECKING_S, "default"
    for c in out:
        # a check that got a slot and then hit the limit compiled for at least the rest of it
        if c.outcome == "timeout" and c.acquire is not None and c.checking_s is not None:
            c.checking_s = max(c.checking_s, c.start + LIMIT_S - c.acquire + 1.0)
    return out


# --- the simulation -------------------------------------------------------------------------


@dataclass
class SimJob:
    key: str
    arrive: float
    checking_s: float
    uses_slot: bool = True
    leave_at: float | None = None
    """An outside departure (killed by an agent, or a known end) at this time, if not done."""
    hold_until_leave: bool = False
    """Once it has a slot it holds it until ``leave_at`` (a check whose real end is known)."""
    phase: float = 0.0
    """Offset of its 1-second scan cycle."""
    deadline: float | None = None
    """When the time limit stops it (default: ``arrive + limit``)."""


@dataclass
class SimResult:
    key: str
    arrive: float
    acquire: float | None
    end: float
    outcome: str
    """done | timeout | left (outside departure) | no_slot | open (still in the system at stop)"""

    @property
    def total(self) -> float:
        return self.end - self.arrive

    @property
    def wait(self) -> float:
        return (self.acquire if self.acquire is not None else self.end) - self.arrive


@dataclass
class SimRun:
    results: dict[str, SimResult] = field(default_factory=dict)

    def waiting_at(self, t: float) -> int:
        """Checks in line (in the system, no slot yet) at time t."""
        n = 0
        for r in self.results.values():
            if r.outcome == "no_slot":
                continue
            got = r.acquire if r.acquire is not None else r.end
            if r.arrive <= t < got:
                n += 1
        return n


def simulate(
    jobs: list[SimJob],
    slots: int,
    limit: float = LIMIT_S,
    poll: float = POLL_S + SCAN_OVERHEAD_S,
    stop: float | None = None,
    held: dict[str, float] | None = None,
) -> SimRun:
    """Run the checker's rules over ``jobs``.

    ``held`` gives jobs that already hold a slot at their arrival (key -> acquire time), for
    starting from a reconstructed state. Events after ``stop`` are not processed; jobs still in
    the system then are reported as ``open`` with ``end = stop``.
    """
    held = held or {}
    seq = 0
    heap: list[tuple[float, int, str, str]] = []

    def push(t: float, kind: str, key: str) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(heap, (t, seq, kind, key))

    byk = {j.key: j for j in jobs}
    res = SimRun()
    free = slots
    holding: set[str] = set()
    waiting: set[str] = set()
    done: set[str] = set()
    scan_planned: float | None = None

    def next_poll(j: SimJob, t: float) -> float:
        base = j.arrive + j.phase
        k = max(1, math.ceil((t - base) / poll - 1e-9))
        return base + k * poll

    def plan_scan(t: float) -> None:
        nonlocal scan_planned
        if free > 0 and waiting:
            tg = min(next_poll(byk[k], t) for k in waiting)
            if scan_planned is None or tg < scan_planned - 1e-9 or scan_planned < t - 1e-9:
                scan_planned = tg
                push(tg, "scan", "")

    def acquire(key: str, t: float) -> None:
        nonlocal free
        j = byk[key]
        free -= 1
        holding.add(key)
        waiting.discard(key)
        res.results[key].acquire = t
        if j.hold_until_leave and j.leave_at is not None:
            return
        finish = t + j.checking_s
        push(finish, "finish", key)

    def leave(key: str, t: float, outcome: str) -> None:
        nonlocal free
        if key in done:
            return
        done.add(key)
        if key in holding:
            holding.discard(key)
            free += 1
        waiting.discard(key)
        r = res.results[key]
        r.end, r.outcome = t, outcome
        plan_scan(t)

    for j in jobs:
        push(j.arrive, "arrive", j.key)

    while heap:
        t, _, kind, key = heapq.heappop(heap)
        if stop is not None and t > stop:
            break
        if kind == "arrive":
            j = byk[key]
            res.results[key] = SimResult(key, j.arrive, None, j.arrive, "open")
            if not j.uses_slot:
                done.add(key)
                res.results[key].end = j.arrive + j.checking_s
                res.results[key].outcome = "no_slot"
                continue
            push(j.deadline if j.deadline is not None else j.arrive + limit, "limit", key)
            if j.leave_at is not None:
                push(j.leave_at, "leave", key)
            if key in held:
                free -= 1
                holding.add(key)
                res.results[key].acquire = held[key]
                if not (j.hold_until_leave and j.leave_at is not None):
                    push(held[key] + j.checking_s, "finish", key)
            elif free > 0:
                acquire(key, t)
            else:
                waiting.add(key)
                plan_scan(t)
        elif kind == "finish":
            if key not in done and key in holding:
                leave(key, t, "done")
        elif kind == "limit":
            if key not in done:
                leave(key, t, "timeout")
        elif kind == "leave":
            if key not in done:
                leave(key, t, "left")
        elif kind == "scan":
            if scan_planned is not None and abs(t - scan_planned) < 1e-9:
                scan_planned = None
            # every waiter whose scan falls at this moment tries; first in arrival order wins
            ready = sorted(
                (k for k in waiting if abs(next_poll(byk[k], t - 1e-9) - t) < 1e-6),
                key=lambda k: (byk[k].arrive, k),  # ties broken by key, never by set order
            )
            for k in ready:
                if free <= 0:
                    break
                acquire(k, t)
            plan_scan(t + 1e-9)
    if stop is not None:
        for k, r in res.results.items():
            if k not in done and r.outcome == "open":
                r.end = stop
    return res


def _phase(key: str, rng: np.random.Generator | None) -> float:
    if rng is not None:
        return float(rng.uniform(0, POLL_S))
    return 0.0


# --- driven validation ----------------------------------------------------------------------


class Occupancy:
    """Fast counts over a run's real record: slot-using checks in flight at a time, and checks
    that finished (with a result, after compiling) in a time window."""

    def __init__(self, checks: list[Check], run_end: float | None = None) -> None:
        users = [c for c in checks if c.uses_slot]
        self.starts = np.sort(np.array([c.start for c in users], dtype=float))
        self.ends = np.sort(np.array([c.real_end(run_end) for c in users], dtype=float))
        fin = sorted(
            (c.end, c.checking_s or 0.0) for c in users if c.outcome in ("ok", "error") and c.end is not None
        )
        self.fin_ends = np.array([f[0] for f in fin], dtype=float)
        self.fin_cum = np.concatenate([[0.0], np.cumsum([f[1] for f in fin])])

    def in_flight(self, t: float) -> int:
        return int(np.searchsorted(self.starts, t, "right") - np.searchsorted(self.ends, t, "right"))

    def finished(self, a: float, b: float) -> tuple[int, float]:
        """How many finished in [a, b), and the sum of their (estimated) checking times."""
        i, j = np.searchsorted(self.fin_ends, a, "left"), np.searchsorted(self.fin_ends, b, "left")
        return int(j - i), float(self.fin_cum[j] - self.fin_cum[i])


def throughput_factor(occ: Occupancy, slots: int, t: float, window: float = 300.0) -> float:
    """How much longer than their estimated checking times checks really held the slots, judged
    from the ``window`` seconds before ``t`` (so only from the past).

    Only when the line was never empty in that window (every sampled moment had at least
    ``slots`` checks in flight): then the slots were always busy, and the time each finished check
    held a slot is about ``slots x window / finished``. The factor is that over the finished
    checks' mean estimated checking time, at least 1. Checks that timed out while holding a slot
    are ignored (few do: most time-outs never got one), so this slightly overstates the factor.
    """
    a = t - window
    if any(occ.in_flight(a + k * window / 20) < slots for k in range(20)):
        return 1.0
    n, total = occ.finished(a, t)
    if n < 5 or total <= 0:
        return 1.0
    hold = slots * window / n
    return max(1.0, hold / (total / n))


def validate_run(
    checks: list[Check],
    slots: int,
    run_end: float | None = None,
    seed: int | None = 0,
    calibrate: bool = False,
) -> list[dict[str, Any]]:
    """Drive the program with each real check's start time and estimated checking time.

    Checks killed by agents leave at their real end time (an outside event). With ``calibrate``,
    each check's checking time is multiplied by ``throughput_factor`` at its start (the slowdown
    seen in the previous 5 minutes; past information only).

    Returns one row per check: the predicted and real time to result, the predicted wait in line,
    whether each hit the limit, how the checking time was found, and whether the check started at
    a busy moment (at least ``slots`` other checks in flight, so it may have waited).
    """
    est = estimate_checking_times(checks, slots, run_end=run_end)
    occ = Occupancy(est, run_end)
    rng = np.random.default_rng(seed) if seed is not None else None
    factors: dict[int, float] = {}
    jobs = []
    for c in est:
        leave_at = c.end if c.outcome == "killed" and c.end is not None else None
        k = 1.0
        if calibrate and c.uses_slot and c.checking_source not in LEARNED:
            grid = int(c.start // 30)
            if grid not in factors:
                factors[grid] = throughput_factor(occ, slots, grid * 30.0)
            k = factors[grid]
        jobs.append(
            SimJob(
                key=c.key,
                arrive=c.arrive,
                checking_s=max(0.0, (c.checking_s or 0.0) * k),
                uses_slot=c.uses_slot,
                leave_at=leave_at,
                phase=_phase(c.key, rng),
                deadline=c.start + LIMIT_S,
            )
        )
    sim = simulate(jobs, slots)
    rows = []
    for c, j in zip(est, jobs):
        r = sim.results[c.key]
        busy = c.uses_slot and occ.in_flight(c.start) - 1 >= slots
        rows.append(
            {
                "key": c.key,
                "agent": c.agent,
                "t_start": c.start,
                "outcome": c.outcome,
                "uses_slot": c.uses_slot,
                "busy_at_start": busy,
                "checking_s": j.checking_s,
                "checking_source": c.checking_source,
                "real_total_s": c.real_total,
                "sim_total_s": (r.end - c.start) if r.outcome in ("done", "timeout", "no_slot") else None,
                "real_wait_s": c.real_wait,
                "sim_wait_s": r.wait if c.uses_slot else 0.0,
                "sim_outcome": r.outcome,
                "real_hit_limit": c.outcome == "timeout",
                "sim_hit_limit": r.outcome == "timeout",
            }
        )
    return rows


def times_off(pred: float | None, real: float | None, floor: float = 1.0) -> float | None:
    """The plan's timing error: how many times too fast or too slow, with times under ``floor``
    seconds counted as ``floor``. 1.0 is exact; 2.0 is a factor of two either way."""
    if pred is None or real is None:
        return None
    return math.exp(abs(math.log(max(pred, floor)) - math.log(max(real, floor))))


def summarise_validation(rows: list[dict[str, Any]], window: float = 300.0) -> dict[str, Any]:
    """How well the driven program matched reality, from ``validate_run``'s rows.

    - ``per_check_*``: the median "times off" between predicted and real time to result, over
      slot-using checks with a known result in both (all of them, and those that started at a
      busy moment). Which waiting check gets a freed slot is down to chance, so per-check errors
      in a long line are large even for a perfect program; the window figures are fairer.
    - ``window_*``: for each 5-minute window with at least 5 such checks, the times off between
      the predicted and real median time to result; the median over windows, and the share of
      windows within a factor of 2.
    - ``wait_*``: for checks whose slot time the process records show, the times off between the
      predicted and the real wait in line (1-second floor), all and at busy moments. This is the
      most direct test of the slot rules.
    - ``real_timeouts`` / ``sim_timeouts`` and ``limit_agreement`` (share of checks where the
      program and reality agree on hitting the limit).
    """
    scored = [
        r for r in rows if r["uses_slot"] and r["real_total_s"] is not None and r["sim_total_s"] is not None
    ]
    off = [times_off(r["sim_total_s"], r["real_total_s"]) for r in scored]
    off_busy = [times_off(r["sim_total_s"], r["real_total_s"]) for r in scored if r["busy_at_start"]]
    by_win: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in scored:
        by_win[int(r["t_start"] // window)].append(r)
    win_off = []
    for rs in by_win.values():
        if len(rs) >= 5:
            win_off.append(
                times_off(_median([r["sim_total_s"] for r in rs]), _median([r["real_total_s"] for r in rs]))
            )
    users = [r for r in rows if r["uses_slot"]]
    waits = [r for r in users if r.get("real_wait_s") is not None and r["sim_outcome"] in ("done", "timeout")]
    w_off = [times_off(r["sim_wait_s"], r["real_wait_s"]) for r in waits]
    w_busy = [times_off(r["sim_wait_s"], r["real_wait_s"]) for r in waits if r["busy_at_start"]]
    return {
        "checks": len(rows),
        "measured_waits": len(waits),
        "wait_median_off": _median(w_off),
        "wait_share_within_2": (sum(x <= 2 for x in w_off) / len(w_off)) if w_off else None,
        "busy_measured_waits": len(w_busy),
        "busy_wait_median_off": _median(w_busy),
        "busy_wait_share_within_2": (sum(x <= 2 for x in w_busy) / len(w_busy)) if w_busy else None,
        "real_median_wait_s": _median([r["real_wait_s"] for r in waits]),
        "sim_median_wait_s": _median([r["sim_wait_s"] for r in waits]),
        "scored": len(scored),
        "busy_scored": len(off_busy),
        "per_check_median_off": _median(off),
        "per_check_busy_median_off": _median(off_busy),
        "windows": len(win_off),
        "window_median_off": _median(win_off),
        "window_share_within_2": (sum(x <= 2 for x in win_off) / len(win_off)) if win_off else None,
        "real_timeouts": sum(r["real_hit_limit"] for r in users),
        "sim_timeouts": sum(r["sim_hit_limit"] for r in users),
        "limit_agreement": (sum(r["real_hit_limit"] == r["sim_hit_limit"] for r in scored) / len(scored))
        if scored
        else None,
    }


# --- frozen moments -------------------------------------------------------------------------


def truth_from_checks(
    checks: list[Check], slots: int, t_freeze: float, run_end: float | None = None, horizon: float = HORIZON_S
) -> dict[str, Any]:
    """The real values the frozen-moment forecasts are scored against.

    - ``real_typical_wait_s``: median time from issuing a check to its result (300 for a
      time-out), over slot-using checks started in the next ``horizon`` seconds whose result is
      known (checks killed by agents are left out). None if there are none.
    - ``real_waiting_5min`` / ``real_waiting_10min``: checks in line (in flight beyond the slot
      count) 5 and 10 minutes later: ``max(0, in flight - slots)``. Every slot is busy whenever
      a check waits, so this is exact up to the 1-second scan.
    - ``real_hits_limit``: whether any check reaches the 300 s limit in the next ``horizon``.
    """
    t1 = t_freeze + horizon
    window = [c for c in checks if c.uses_slot and t_freeze < c.start <= t1]
    totals = [c.real_total for c in window if c.real_total is not None]
    timeouts = [c for c in checks if c.outcome == "timeout" and t_freeze < c.start + LIMIT_S <= t1]

    def waiting(t: float) -> int | None:
        if run_end is not None and t > run_end:
            return None
        return max(0, in_flight(checks, t, run_end) - slots)

    return {
        "slots": slots,
        "real_typical_wait_s": _median(totals),
        "real_waiting_5min": waiting(t_freeze + horizon / 2),
        "real_waiting_10min": waiting(t1),
        "real_hits_limit": bool(timeouts),
        "real_n_timeouts": len(timeouts),
        "real_n_checks_next10": len(window),
    }


def state_from_checks(
    checks: list[Check], slots: int, t_freeze: float, run_end: float | None = None
) -> dict[str, Any]:
    """What is known at a frozen moment: checks in flight (by agent, with how long they have
    been running), and how many of them must be waiting (in flight beyond the slot count).

    Uses only what was knowable then: a check is in flight if it was called by the freeze and its
    result had not come back (nor its 300 s run out). Whether it will need a slot is not known
    yet, so every checker call in flight counts.
    """
    flying = [c for c in checks if c.start <= t_freeze and not ended_by(c, t_freeze, run_end)]
    return {
        "slots": slots,
        "in_flight": len(flying),
        "waiting": max(0, len(flying) - slots),
        "checks": [
            {"key": c.key, "agent": c.agent, "file": c.file, "elapsed_s": t_freeze - c.start}
            for c in sorted(flying, key=lambda c: c.start)
        ],
    }


def forecast_from_checks(
    checks: list[Check],
    slots: int,
    t_freeze: float,
    run_end: float | None = None,
    horizon: float = HORIZON_S,
    reps: int = 200,
    seed: int = 0,
    lookback: float = HORIZON_S,
    calibrate: bool = True,
) -> dict[str, Any]:
    """The program's forecast for the next ``horizon`` seconds, from what was known at ``t_freeze``.

    It knows: every check started before the freeze, the end time and result of those that had
    ended, and how long the others have been in flight. It assumes:

    - **The past up to the freeze** is replayed with the checker's rules, holding each ended check
      until its real end, to find which in-flight checks hold slots.
    - **In-flight checks** need their estimated checking time (learned only from checks that
      ended before the freeze); one already compiling longer than that needs a further quarter of
      it, at least 5 s.
    - **New checks** arrive at each agent's rate over the previous ``lookback`` seconds (random,
      evenly spread), until ``run_end``. Each takes a checking time drawn from the no-wait checks
      of the 20 minutes before the freeze (all before it, if fewer than 10).
    - With ``calibrate`` (the default), checking times are multiplied by ``throughput_factor`` at
      the freeze: if the slots were full for the last 5 minutes, how much longer than expected
      checks held them.
    - Agents kill nothing.

    Returns the median over ``reps`` random futures: ``sim_typical_wait_s``,
    ``sim_waiting_5min``, ``sim_waiting_10min``, ``sim_hits_limit`` (true when more than half the
    futures have a check reach the limit), plus ``sim_hits_limit_prob``.
    """
    # what was known at the freeze: checks still in flight have no end and no result yet
    past = []
    for c in checks:
        if c.start > t_freeze:
            continue
        if not ended_by(c, t_freeze):
            c = replace(c, end=None, outcome="unknown")
        if c.acquire is not None and c.acquire > t_freeze:
            c = replace(c, acquire=None)
        if c.lc_start is not None and c.lc_start > t_freeze:
            c = replace(c, lc_start=None)
        past.append(c)
    est = estimate_checking_times(past, slots, cutoff=t_freeze, run_end=run_end)
    known_end = {c.key: c.real_end(run_end) for c in est if c.outcome != "unknown"}

    # 1. replay the past to find who holds a slot at the freeze
    jobs = []
    for c in est:
        deadline = c.start + LIMIT_S
        if c.key in known_end:
            jobs.append(
                SimJob(c.key, c.arrive, c.checking_s or 0.0, c.uses_slot, known_end[c.key], True, deadline=deadline)
            )
        else:
            # still in flight at the freeze: it cannot end before then
            jobs.append(SimJob(c.key, c.arrive, 1e9, c.uses_slot, deadline=deadline))
    hist = simulate(jobs, slots, stop=t_freeze)
    flying = [c for c in est if c.uses_slot and c.key not in known_end]
    holding = {
        c.key: hist.results[c.key].acquire
        for c in flying
        if c.key in hist.results and hist.results[c.key].acquire is not None
    }
    # where the process records show who held a slot at the freeze, believe them
    measured = {c.key: c.acquire for c in flying if c.acquire is not None}
    guessed = [(k, t) for k, t in holding.items() if k not in measured]
    holding = dict(sorted(measured.items(), key=lambda kv: kv[1]) + guessed)
    if len(holding) > slots:
        holding = dict(list(holding.items())[:slots])

    pool_recent = [
        c.checking_s for c in est if c.checking_source in LEARNED and c.end and c.end > t_freeze - 1200
    ]
    pool_all = [c.checking_s for c in est if c.checking_source in LEARNED]
    pool = pool_recent if len(pool_recent) >= 10 else (pool_all or [DEFAULT_CHECKING_S])
    factor = throughput_factor(Occupancy(est, run_end), slots, t_freeze) if calibrate else 1.0
    pool = [x * factor for x in pool]
    window_start = max(t_freeze - lookback, min((c.start for c in checks), default=t_freeze))
    span = max(t_freeze - window_start, 60.0)
    rates: dict[str, float] = defaultdict(float)
    for c in past:  # outcomes of checks still in flight at the freeze are not known yet
        if window_start < c.start <= t_freeze and c.uses_slot:
            rates[c.agent] += 1.0 / span
    stop_arrivals = t_freeze + horizon if run_end is None else min(t_freeze + horizon, run_end)

    rng = np.random.default_rng(seed)
    typ, w5, w10, hits = [], [], [], []
    for _ in range(reps):
        jobs = []
        held: dict[str, float] = {}
        for c in flying:
            elapsed_run = t_freeze - holding[c.key] if c.key in holding else 0.0
            need = (c.checking_s or DEFAULT_CHECKING_S) * factor
            remaining = need - elapsed_run if need > elapsed_run else max(0.25 * need, 5.0)
            if c.key in holding:
                held[c.key] = t_freeze
            jobs.append(SimJob(c.key, c.start, remaining, True, phase=float(rng.uniform(0, POLL_S))))
        new_keys = []
        for agent, rate in rates.items():
            t = t_freeze
            while True:
                t += float(rng.exponential(1.0 / rate))
                if t > stop_arrivals:
                    break
                k = f"new/{agent}/{len(new_keys)}"
                new_keys.append(k)
                jobs.append(SimJob(k, t, float(rng.choice(pool)), True, phase=float(rng.uniform(0, POLL_S))))
        # in-flight jobs start from the freeze: shift their arrival so the limit stays right
        sim = _simulate_from(jobs, slots, held, t_freeze, stop=t_freeze + horizon + LIMIT_S)
        new_totals = [
            sim.results[k].total for k in new_keys if sim.results[k].outcome in ("done", "timeout")
        ]
        typ.append(_median(new_totals))
        w5.append(sim.waiting_at(t_freeze + horizon / 2))
        w10.append(sim.waiting_at(t_freeze + horizon))
        hits.append(
            any(
                r.outcome == "timeout" and t_freeze < r.end <= t_freeze + horizon
                for r in sim.results.values()
            )
        )
    typ_known = [x for x in typ if x is not None]
    p_hit = float(np.mean(hits)) if hits else 0.0
    return {
        "sim_typical_wait_s": _median(typ_known),
        "sim_waiting_5min": round(float(statistics.median(w5))) if w5 else None,
        "sim_waiting_10min": round(float(statistics.median(w10))) if w10 else None,
        "sim_hits_limit": p_hit > 0.5,
        "sim_hits_limit_prob": p_hit,
    }


def _simulate_from(
    jobs: list[SimJob], slots: int, held: dict[str, float], t0: float, stop: float
) -> SimRun:
    """Simulate from ``t0`` with some jobs already in the system (arrived before ``t0``).

    Jobs that arrived earlier enter at ``t0`` (holding a slot if in ``held``) but keep their
    real arrival time for the limit and for reporting.
    """
    shifted = []
    original: dict[str, float] = {}
    for j in jobs:
        if j.arrive < t0:
            original[j.key] = j.arrive
            shifted.append(replace(j, arrive=t0, phase=(j.arrive + j.phase - t0) % POLL_S))
        else:
            shifted.append(j)
    # the limit counts from the real arrival: give early arrivals a shorter limit via leave_at
    for i, j in enumerate(shifted):
        if j.key in original:
            deadline = original[j.key] + LIMIT_S
            shifted[i] = replace(j, leave_at=max(t0, deadline))
    sim = simulate(shifted, slots, held={k: t0 for k in held}, stop=stop)
    for k, a in original.items():
        r = sim.results.get(k)
        if r is None:
            continue
        r.arrive = a
        if r.outcome == "left":  # it reached its real deadline
            r.outcome = "timeout"
    return sim


# --- the real runs --------------------------------------------------------------------------


def default_runs_dir() -> Path:
    """The main checkout's runs folder, also from inside a worktree (.claude/worktrees/<name>)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "worktrees" and parent.parent.name == ".claude":
            return parent.parent.parent / "runs"
    return here.parents[4] / "runs"


def study_dir() -> Path:
    """The study's shared data folder (``runs/_studies/auditor``)."""
    return default_runs_dir() / "_studies" / "auditor"


@dataclass
class RunQueue:
    run_id: str
    slots: SlotInfo
    checks: list[Check]
    run_start: float
    run_end: float
    """When the run's record ends (its last command, result or request)."""


_COMMANDS_CACHE: dict[str, Any] = {}


COMMAND_COLUMNS = [
    "key", "run_id", "scenario", "agent", "command", "output", "output_status",
    "t_call", "t_result", "t_seen", "duration_s",
]


def load_commands(path: Path | None = None):
    """The proof-conference rows of the commands table, only the columns needed here (cached)."""
    import pandas as pd

    path = path or study_dir() / "commands.parquet"
    key = str(path)
    if key not in _COMMANDS_CACHE:
        df = pd.read_parquet(path, columns=COMMAND_COLUMNS)
        _COMMANDS_CACHE[key] = df[df["scenario"].str.startswith("proof-conference")].reset_index(drop=True)
    return _COMMANDS_CACHE[key]


def proof_run_ids(commands=None) -> list[str]:
    """Runs whose agents used the proof checker (the proof conference and its variants)."""
    df = load_commands() if commands is None else commands
    ids = sorted(df.loc[df["scenario"].str.startswith("proof-conference"), "run_id"].unique())
    return [i for i in ids if (default_runs_dir() / i / "compose.yaml").exists()]


_RUN_CACHE: dict[tuple[str, int], RunQueue] = {}


def load_run(run_id: str, commands=None, runs_dir: Path | None = None, procs: bool = True) -> RunQueue:
    """One run's checks, slot count and time span (cached per commands table). With ``procs``,
    checks get their measured slot times from the process records (read from the run's Inspect
    log once, then cached in the study folder)."""
    df = load_commands() if commands is None else commands
    ck = (run_id, id(df))
    if ck in _RUN_CACHE:
        return _RUN_CACHE[ck]
    rows = df[df["run_id"] == run_id]
    times = [
        _ts(x)
        for col in ("t_call", "t_result", "t_seen")
        if col in rows
        for x in rows[col].dropna().tolist()
    ]
    times = [t for t in times if t is not None]
    rq = RunQueue(
        run_id=run_id,
        slots=run_slots((runs_dir or default_runs_dir()) / run_id),
        checks=checks_from_rows(rows.to_dict("records")),
        run_start=min(times),
        run_end=max(times),
    )
    if procs:
        rq.checks = attach_slot_times(rq.checks, cached_proc_records(run_id, runs_dir))
        rq.checks.sort(key=lambda c: c.start)
    _RUN_CACHE[ck] = rq
    return rq


def queue_truth(run_id: str, t_freeze: Any, commands=None) -> dict[str, Any]:
    """The real queue values after a frozen moment of a run (see ``truth_from_checks``)."""
    rq = load_run(run_id, commands)
    return truth_from_checks(rq.checks, rq.slots.slots, _ts(t_freeze), rq.run_end)


def queue_state_at(run_id: str, t_freeze: Any, commands=None) -> dict[str, Any]:
    """What is in flight at a frozen moment (see ``state_from_checks``)."""
    rq = load_run(run_id, commands)
    return state_from_checks(rq.checks, rq.slots.slots, _ts(t_freeze), rq.run_end)


def queue_forecast(run_id: str, t_freeze: Any, commands=None, reps: int = 200, seed: int = 0) -> dict[str, Any]:
    """The program's forecast at a frozen moment of a run (see ``forecast_from_checks``)."""
    rq = load_run(run_id, commands)
    return forecast_from_checks(rq.checks, rq.slots.slots, _ts(t_freeze), rq.run_end, reps=reps, seed=seed)


# --- process records: when each check really got a slot ---------------------------------------
#
# swarmbench's container watcher records every new process ({pid, ppid, uid, cmd, t}, t = start
# time) and the monitor reads them with ``acctd --dump``; each read is an Inspect "sandbox" event
# whose output holds the new rows. A check shows up as "/bin/sh .../lean-check FILE" (the agent's
# uid). Once it has a slot, the subshell holding the lock execs "lake env lean ... FILE", which
# starts "lean ... FILE"; lean-check starts neither before it holds a lock. So the first lake/lean
# under a lean-check marks when the check got its slot. There are no exit records. Inspect keeps
# only the first 10,000 characters of each event's output, so busy runs lose most rows; rows up
# to the cut are kept here.

_PROCS_DATA = re.compile(r'"procs\.jsonl":\s*\{"size":\s*\d+,\s*"data":\s*"')


def parse_proc_dump(output: str) -> list[dict[str, Any]]:
    """Process rows from one ``acctd --dump`` output, also when Inspect cut it short."""
    m = _PROCS_DATA.search(output or "")
    if not m:
        return []
    raw = output[m.end():]
    # the data string ends at the first unescaped quote; if it was cut, keep the complete rows
    end = None
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            end = i
            break
        i += 1
    if end is None:
        cut = raw.rfind("}\\n")
        if cut < 0:
            return []
        raw = raw[: cut + 3]
    else:
        raw = raw[:end]
    try:
        text = json.loads('"' + raw + '"')
    except ValueError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and {"pid", "ppid", "uid", "cmd", "t"} <= set(r):
            rows.append(r)
    return rows


def read_proc_records(eval_path: Path | str, keep: re.Pattern[str] | None = None) -> list[dict[str, Any]]:
    """All process rows the monitor read during a run (deduplicated), optionally only those whose
    command matches ``keep``."""
    from inspect_ai.log import read_eval_log

    log = read_eval_log(str(eval_path), resolve_attachments=True)
    seen: dict[tuple[int, float], dict[str, Any]] = {}
    for sample in log.samples or []:
        for e in sample.events or []:
            if getattr(e, "event", None) != "sandbox" or not getattr(e, "output", None):
                continue
            if "acctd" not in (getattr(e, "cmd", "") or "") or "procs.jsonl" not in e.output:
                continue
            for r in parse_proc_dump(e.output):
                if keep is None or keep.search(r["cmd"]):
                    seen[(r["pid"], r["t"])] = r
    return sorted(seen.values(), key=lambda r: r["t"])


_CHECKER_PROC = re.compile(r"lean-check|\blake\b|(?:^|/)lean\s|/conference/bin/submit")


def cached_proc_records(run_id: str, runs_dir: Path | None = None, refresh: bool = False) -> list[dict[str, Any]]:
    """A run's checker-related process rows, cached in the study folder
    (``queue_procs/<run_id>.json``; regenerable from the run's Inspect log)."""
    cache = study_dir() / "queue_procs" / f"{run_id}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    rows: list[dict[str, Any]] = []
    for log in sorted(((runs_dir or default_runs_dir()) / run_id / "logs").glob("*.eval")):
        rows.extend(read_proc_records(log, _CHECKER_PROC))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows


def _proc_file(cmd: str) -> str | None:
    m = re.search(r"(\S+\.lean)\s*$", cmd.strip())
    return m.group(1).rsplit("/", 1)[-1] if m else None


def _is_lean_check(r: dict[str, Any] | None) -> bool:
    if r is None:
        return False
    cmd = r["cmd"].lstrip()
    return "lean-check" in cmd and not cmd.startswith(("lake", "lean ")) and "grep" not in cmd




MAX_START_LAG_S = 10.0
"""A ``lean-check`` process counts as a check's start only within this long after the call
(normally 0.1-0.3 s). Later ones are the lock subshells a waiting check forks every second, seen
when the record of their parent was lost."""


def slot_times(procs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """From process rows: the ``lean-check`` processes and the slot acquisitions.

    Returns (checkers, acquisitions). A checker is {uid, file, t, pid, ppid, parent_known,
    parent_is_checker}. An acquisition is {uid, file, t, parent}: a compiler (lake, or the lock
    subshell seen before it became lake) and the pid of the ``lean-check`` it runs under. Compiles
    under a known parent that is not ``lean-check`` (an agent running ``lake env lean`` itself)
    are left out.
    """
    by_pid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in procs:
        by_pid[r["pid"]].append(r)

    def proc_at(pid: int, t: float) -> dict[str, Any] | None:
        """The process with this pid that started last at or before t (pids are reused)."""
        best = None
        for r in by_pid.get(pid, []):
            if r["t"] <= t + 0.5 and (best is None or r["t"] > best["t"]):
                best = r
        return best

    checkers = []
    for r in procs:
        if not _is_lean_check(r):
            continue
        parent = proc_at(r["ppid"], r["t"])
        checkers.append(
            {
                "uid": r["uid"],
                "file": _proc_file(r["cmd"]),
                "t": r["t"],
                "pid": r["pid"],
                "ppid": r["ppid"],
                "parent_known": parent is not None,
                "parent_is_checker": _is_lean_check(parent),
            }
        )

    holders: dict[tuple[int, float], dict[str, Any]] = {}
    for r in procs:
        cmd = r["cmd"].lstrip()
        if cmd.startswith("lake env lean"):
            holder = r
        elif cmd.startswith("lean "):
            parent = proc_at(r["ppid"], r["t"])
            if parent is None or not (parent["cmd"].lstrip().startswith("lake") or _is_lean_check(parent)):
                continue
            holder = parent
        else:
            continue
        main = proc_at(holder["ppid"], holder["t"])
        if main is not None and not _is_lean_check(main):
            continue  # an agent's own compile, outside the slots
        holders.setdefault(
            (holder["pid"], holder["t"]),
            {"uid": holder["uid"], "file": _proc_file(r["cmd"]), "t": holder["t"], "parent": holder["ppid"]},
        )
    return checkers, sorted(holders.values(), key=lambda a: a["t"])


def agent_uid(agent: str) -> int | None:
    """The proof-conference agent ``agent-N`` runs as user uNN, uid 2000 + N."""
    m = re.search(r"(\d+)$", agent or "")
    return 2000 + int(m.group(1)) if m else None


def _same_file(a: str | None, b: str | None) -> bool:
    # submit checks a private temporary copy, so a "tmp*.lean" name matches anything
    return a is None or b is None or a == b or a.startswith("tmp") or b.startswith("tmp")


def attach_slot_times(checks: list[Check], procs: list[dict[str, Any]]) -> list[Check]:
    """Fill in ``lc_start`` and ``acquire`` for the checks the process records cover.

    For each check that runs the checker once, in call order:

    - its ``lean-check`` process is the first unused one of its agent's uid and file that is not
      a lock subshell and started within ``MAX_START_LAG_S`` of the call (``lc_start``);
    - the pids it may run under are that process's, plus the parents of lock subshells of its
      uid and file seen during its life whose own parent's record was lost;
    - its slot time (``acquire``) is the first unused acquisition under one of those pids during
      its life.
    """
    checkers, acqs = slot_times(procs)
    ck_by_uid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for s in checkers:
        ck_by_uid[s["uid"]].append(s)
    acq_by_uid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for a in acqs:
        acq_by_uid[a["uid"]].append(a)
    used_main: set[int] = set()
    used_acq: set[int] = set()
    claimed_pids: set[tuple[int, int]] = set()
    out = []
    for c in sorted(checks, key=lambda c: c.start):
        c = replace(c)
        out.append(c)
        uid = agent_uid(c.agent)
        if uid is None or c.n_invocations != 1 or not c.uses_slot:
            continue
        end = c.real_end()
        mine = [s for s in ck_by_uid.get(uid, []) if c.start - 0.5 <= s["t"] <= end and _same_file(c.file, s["file"])]
        main = next(
            (
                s
                for s in mine
                if id(s) not in used_main and not s["parent_is_checker"] and s["t"] <= c.start + MAX_START_LAG_S
            ),
            None,
        )
        pids: set[int] = set()
        if main is not None:
            used_main.add(id(main))
            c.lc_start = main["t"]
            pids.add(main["pid"])
        for s in mine:
            if s is main or s["parent_is_checker"]:
                continue
            if not s["parent_known"] and s["t"] > c.start + MAX_START_LAG_S:
                pids.add(s["ppid"])  # a lock subshell whose parent's record was lost
        pids = {p for p in pids if (uid, p) not in claimed_pids or p == (main or {}).get("pid")}
        lo = c.arrive
        for a in acq_by_uid.get(uid, []):
            if id(a) in used_acq or not (lo - 0.5 <= a["t"] <= end + 0.5) or a["parent"] not in pids:
                continue
            if not _same_file(c.file, a["file"]):
                continue
            used_acq.add(id(a))
            c.acquire = a["t"]
            break
        claimed_pids |= {(uid, p) for p in pids}
    return out
