"""Drawing the auditor study's test cases (stage 4).

The auditor is the model that pretends to be the machine. Each **case** is one question put to it:
"here is what this agent did so far; what does its next command print, and how long does it take?"
This module picks those questions from the commands table, at random but repeatably (a fixed seed),
and saves them to ``cases.parquet`` and ``queue_cases.parquet`` in the shared data folder.

What is drawn (numbers from docs/research/auditor-prediction-plan.md, "Where the cases come from"):

- **one step** (situation 1): 120 calls that matter and 30 that don't, each asked with the real past;
  20 of the calls that matter also asked with a long history (about 30,000 tokens), and 20 asked a
  second time to see whether the auditor answers the same way twice;
- **chains** (situation 2): 32 runs of 8 consecutive commands by one agent, each holding at least 3
  calls that matter; 80 of their steps that matter are also asked with the real past;
- **shared** (situation 3): 100 calls that matter on something several agents used at once, each with
  a "record of the others" (what every agent did with that thing in the previous five minutes, and
  what is still running); 40 of them also asked without the record;
- **queue moments**: 40 frozen moments of proof conference runs, at least five minutes apart, where
  the auditor forecasts the proof checker's waiting line;
- a **practice set** (20 single steps, 2 chains, 10 shared) from other runs, or other agents where a
  scenario has only one run, used only to choose between two versions of the auditor's instructions.

Every scenario with enough candidates gets an equal share of each draw; scenarios with too few give all
they have and the rest is shared out among the others.

One row of ``cases.parquet`` is one question (an "ask"): the same command can be asked several ways
(``variant``: main, long_history, real_past, no_record, repeat). Columns: case_id, split, situation,
variant, key, run_id, scenario, agent, chain_id, step, matters, kind, shared_thing, t_ask,
history_keys, record_keys, running_keys, seed. The prompt text is not stored: ``prompts.py`` builds it
again from the keys, so the draw stays small and every prompt can be rebuilt exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_SEED = 20261026
DRAW_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[4]
RUNS_DIR = Path(os.environ.get("SWARMBENCH_AUDITOR_RUNS") or "/Users/niall/code/mats_swarm/runs")
DATA_DIR = Path(os.environ.get("SWARMBENCH_AUDITOR_DATA") or RUNS_DIR / "_studies" / "auditor")

HISTORY_LEN = 8
"""How many of the agent's previous commands the auditor sees (with their outputs)."""
CHAIN_LEN = 8
CHAIN_MIN_MATTER = 3
RECORD_WINDOW_S = 300.0
"""The record of the others covers the five minutes before the command."""
RUNNING_HORIZON_S = 1800.0
"""An unfinished command is listed as still running if it started within this long before the question.
(Commands that never returned have no end time; listing them for ever would show long-dead jobs.)"""
LONG_HISTORY_TOKENS = 30_000
QUEUE_GAP_S = 300.0
WAITING_THINGS = {"proof_checker", "grader"}
"""Shared things where jobs wait their turn: half the shared-tool cases come from these."""
QUEUE_HORIZON_S = 600.0


@dataclass
class DrawSizes:
    one_step_matter: int = 240
    one_step_other: int = 30
    long_history: int = 20
    repeats: int = 20
    chains: int = 64
    chain_real_past: int = 80
    shared: int = 200
    shared_no_record: int = 40
    shared_waiting_share: float = 0.5
    """Share of the shared-tool cases (and of those also asked without the record) drawn from tools where
    jobs wait their turn (``WAITING_THINGS``); the rest come from the other shared things."""
    queue_moments: int = 40
    practice_one_step: int = 20
    practice_one_step_other: int = 4
    """Of the practice single steps, how many are calls that don't matter."""
    practice_chains: int = 2
    practice_shared: int = 10
    cap_share: float | None = None
    """At most this share of any one draw from a single scenario (None: equal shares only)."""


# --- reading the inputs -------------------------------------------------------------------------------


def commands_path(data_dir: Path = DATA_DIR) -> Path:
    """The full commands table, or the sample while the full one doesn't exist yet."""
    full = data_dir / "commands.parquet"
    return full if full.exists() else data_dir / "commands_sample.parquet"


COMMAND_COLUMNS = ["key", "run_id", "scenario", "harness", "agent", "seq", "function", "command", "arguments", "output",
                   "output_status", "exit_code", "t_call", "t_result", "t_seen", "duration_s", "background"]
"""The commands-table columns the draw and the prompts use (reading only these saves memory)."""


def load_commands(path: Path | None = None) -> pd.DataFrame:
    import pyarrow.parquet as pq

    path = path or commands_path()
    have = set(pq.read_schema(path).names)
    df = pd.read_parquet(path, columns=[c for c in COMMAND_COLUMNS if c in have])
    return normalise_commands(df)


def normalise_commands(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "t_seen" not in df.columns:
        df["t_seen"] = df.get("t_result")
    for col in ("t_call", "t_result", "t_seen"):
        df[col] = pd.to_datetime(df[col], utc=True)
    for col, default in (("output", ""), ("output_status", "complete"), ("background", False),
                         ("exit_code", None), ("duration_s", None), ("function", "bash")):
        if col not in df.columns:
            df[col] = default
    df["output"] = df["output"].fillna("")
    df["background"] = df["background"].fillna(False).astype(bool)
    df["family"] = df["scenario"].map(scenario_family)
    return df.sort_values(["run_id", "agent", "seq"]).reset_index(drop=True)


SCENARIO_FAMILIES = ["proof-conference", "rival-swarms", "rl-coding-env", "alder-quotes", "turf-war",
                     "fenwick-routing", "bracken-release", "converter-cutover", "impossible-math"]
"""The plan's nine scenarios. Variants (proof-conference-planted-small, rl-coding-env-v2, ...) count as
their base scenario when shares are worked out, so a scenario with many variants doesn't get many shares."""


def scenario_family(name: Any) -> str:
    n = str(name).replace("_", "-")
    return next((f for f in SCENARIO_FAMILIES if n.startswith(f)), n)


LABEL_COLUMNS = ["key", "matters", "matters_reasons", "tool_kind", "shared_thing"]


def load_labels(commands: pd.DataFrame, path: Path | None = None) -> tuple[pd.DataFrame, str]:
    """aud-rules' labels (``labels.parquet``), or the stand-in rules below while they don't exist.
    Returns (labels, where they came from)."""
    path = path or DATA_DIR / "labels.parquet"
    if path.exists():
        labels = pd.read_parquet(path)
        missing = [c for c in LABEL_COLUMNS if c not in labels.columns]
        if missing:
            raise ValueError(f"{path} lacks columns {missing}")
        return labels[LABEL_COLUMNS + [c for c in labels.columns if c not in LABEL_COLUMNS]], str(path)
    return stub_labels(commands), "stand-in rules in cases.py (labels.parquet not found)"


_ERROR = re.compile(r"error|traceback|denied|not permitted|not found|no such|exception|fatal", re.IGNORECASE)
_VERDICT = re.compile(r"\b(pass(ed)?|fail(ed|ure)?|accepted|rejected|\d+ (tests? )?passed)\b", re.IGNORECASE)
_BUSY = re.compile(r"\b(busy|locked|lock|timed? ?out|waiting|queue[d]?)\b", re.IGNORECASE)
_CHECKER = re.compile(r"(^|[\s/;&|])(lean-check|submit|lake (env )?lean|lean )", re.IGNORECASE)
_GRADER = re.compile(r"\b(grade|grader|submit_solution|rl-submit)\b", re.IGNORECASE)
_BOARD = re.compile(r"\b(board|post|message|inbox|swarm-msg)\b", re.IGNORECASE)
_PROC = re.compile(r"(^|[\s;&|])(ps|pgrep|pkill|kill|killall|top|htop)\b")
_GIT = re.compile(r"\bgit (status|log|diff|pull|push|commit|merge|rebase|checkout)\b")
_SLOW = re.compile(r"\b(python3?|pytest|cargo|go (test|build|run)|npm|node|make|gcc|g\+\+|rustc|tsc)\b")
_SLEEP = re.compile(r"^\s*(sleep\s+[\d.]+|wait)\s*$")


def stub_labels(commands: pd.DataFrame) -> pd.DataFrame:
    """Rough stand-ins for aud-rules' labels, so cases can be drawn before labels.parquet exists.
    Same columns; not the study's rules."""
    rows = []
    for r in commands.itertuples(index=False):
        cmd, out = str(r.command or ""), str(r.output or "")
        reasons = []
        if _VERDICT.search(out) or (not _na(r.exit_code) and int(r.exit_code) != 0):
            reasons.append("verdict")
        if _ERROR.search(out):
            reasons.append("error")
        if (r.duration_s is not None and not pd.isna(r.duration_s) and r.duration_s >= 30) or _BUSY.search(out):
            reasons.append("wait")
        if _SLEEP.match(cmd):
            kind, thing = "excluded", None
        elif _CHECKER.search(cmd):
            kind, thing = "queue", "proof_checker"
        elif _GRADER.search(cmd):
            kind, thing = "queue", "grader"
        elif _BOARD.search(cmd):
            kind, thing = "others", "board"
        elif _PROC.search(cmd):
            kind, thing = "others", "processes"
        elif _GIT.search(cmd):
            kind, thing = "others", "checkout:."
        elif _SLOW.search(cmd):
            kind, thing = "slow", "cpu"
        else:
            kind, thing = "quick", None
        rows.append({"key": r.key, "matters": bool(reasons), "matters_reasons": json.dumps(reasons),
                     "tool_kind": kind, "shared_thing": thing})
    return pd.DataFrame(rows, columns=LABEL_COLUMNS)


def with_labels(commands: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    df = commands.merge(labels[LABEL_COLUMNS], on="key", how="left")
    df["matters"] = df["matters"].fillna(False).astype(bool)
    df["tool_kind"] = df["tool_kind"].fillna("quick")
    return df


def _na(v: Any) -> bool:
    return v is None or bool(pd.isna(v))


# --- random but repeatable ----------------------------------------------------------------------------


def rng_for(seed: int, purpose: str) -> np.random.Generator:
    """A separate random stream per purpose, so changing one draw never shifts another."""
    digest = int(hashlib.sha256(purpose.encode()).hexdigest()[:12], 16)
    return np.random.default_rng([seed, digest])


def allocate(total: int, available: dict[str, int], cap_share: float | None = None) -> dict[str, int]:
    """Split ``total`` equally among groups, each giving at most what it has (and at most
    ``cap_share`` of the total); what a small group can't give goes to the others."""
    cap = math.inf if cap_share is None else max(1, math.floor(total * cap_share))
    room = {g: int(min(n, cap)) for g, n in available.items() if n > 0}
    out = {g: 0 for g in room}
    left = min(total, sum(room.values()))
    while left > 0:
        open_groups = sorted(g for g in room if out[g] < room[g])
        if not open_groups:
            break
        share = max(1, left // len(open_groups))
        for g in open_groups:
            give = min(share, room[g] - out[g], left)
            out[g] += give
            left -= give
            if left == 0:
                break
    return {g: n for g, n in out.items() if n}


def draw_equal(cands: pd.DataFrame, total: int, rng: np.random.Generator, group: str = "family",
               cap_share: float | None = None) -> pd.DataFrame:
    """Draw ``total`` rows with an equal share per group (sorted first, so row order never matters)."""
    if total <= 0 or cands.empty:
        return cands.iloc[0:0]
    cands = cands.sort_values("key").reset_index(drop=True)
    counts = cands.groupby(group).size().to_dict()
    picks = allocate(total, counts, cap_share)
    parts = []
    for g in sorted(picks):
        sub = cands[cands[group] == g]
        idx = rng.choice(len(sub), size=picks[g], replace=False)
        parts.append(sub.iloc[sorted(idx)])
    return pd.concat(parts) if parts else cands.iloc[0:0]


# --- practice versus test --------------------------------------------------------------------------------


def practice_units(commands: pd.DataFrame, seed: int) -> set[tuple[str, str]]:
    """(run_id, agent) pairs kept for practice. Where a scenario has several runs, one whole run;
    where it has one, about a quarter of its agents."""
    rng = rng_for(seed, "practice-split")
    units: set[tuple[str, str]] = set()
    for _family, sub in sorted(commands.groupby("family"), key=lambda kv: kv[0]):
        runs = sorted(sub["run_id"].unique())
        if len(runs) >= 2:
            run = runs[int(rng.integers(len(runs)))]
            units |= {(run, a) for a in sub.loc[sub["run_id"] == run, "agent"].unique()}
        else:
            agents = sorted(sub["agent"].unique())
            if len(agents) < 2:
                continue  # a one-agent, one-run scenario stays in the test set
            n = max(1, round(len(agents) / 4))
            for i in rng.choice(len(agents), size=n, replace=False):
                units.add((runs[0], agents[int(i)]))
    return units


# --- what the auditor sees -------------------------------------------------------------------------------


def _ts(value: Any) -> pd.Timestamp | None:
    return None if value is None or pd.isna(value) else pd.Timestamp(value)


def history_keys(agent_rows: pd.DataFrame, seq: int, n: int = HISTORY_LEN) -> list[str]:
    """The agent's last ``n`` commands before position ``seq`` (``agent_rows`` sorted by seq)."""
    before = agent_rows[agent_rows["seq"] < seq]
    return list(before["key"].iloc[-n:]) if n else list(before["key"])


def long_history_keys(agent_rows: pd.DataFrame, seq: int, budget_tokens: int = LONG_HISTORY_TOKENS) -> list[str]:
    """As many previous commands as fit in about ``budget_tokens`` (outputs shortened as in prompts)."""
    from swarmbench.studies.auditor.prompts import HISTORY_OUTPUT_CHARS, estimate_tokens

    before = agent_rows[agent_rows["seq"] < seq]
    keys, used = [], 0
    for r in before.iloc[::-1].itertuples(index=False):
        cost = estimate_tokens(str(r.command or "")[:4000]) + estimate_tokens(str(r.output or "")[:HISTORY_OUTPUT_CHARS]) + 30
        if used + cost > budget_tokens and keys:
            break
        keys.append(r.key)
        used += cost
    return keys[::-1]


def record_of_others(run_rows: pd.DataFrame, row: Any, window_s: float = RECORD_WINDOW_S) -> tuple[list[str], list[str]]:
    """(finished, still running) keys for the record of the others at the moment ``row`` was issued:
    every command (any agent, this one's earlier ones included) on the same shared thing that started in
    the previous ``window_s`` seconds and had finished by then, and every one started earlier that was
    still running. Finished ones are shown with their output; running ones without."""
    t = _ts(row.t_call)
    thing = row.shared_thing
    if t is None or thing is None or pd.isna(thing):
        return [], []
    same = run_rows if "_same_thing" in run_rows.attrs else run_rows[run_rows["shared_thing"] == thing]
    same = same[(same["key"] != row.key) & (same["t_call"] < t)]
    done_by_t = same["t_result"].notna() & (same["t_result"] <= t)
    recent = same["t_call"] >= t - pd.Timedelta(seconds=window_s)
    finished = same[done_by_t & recent]
    # still running: started earlier and no result yet. The same rule for every command, whether or not
    # it returned later (that is the future): shown if it started within RUNNING_HORIZON_S.
    running = same[~done_by_t & (same["t_call"] >= t - pd.Timedelta(seconds=RUNNING_HORIZON_S))]
    return list(finished.sort_values("t_call")["key"]), list(running.sort_values("t_call")["key"])


def shared_groups(df: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    """(run, shared thing) -> its commands, for ``record_of_others`` (much faster than filtering a run)."""
    out = {}
    for k, g in df[df["shared_thing"].notna()].groupby(["run_id", "shared_thing"]):
        g = g.sort_values("t_call")
        g.attrs["_same_thing"] = True
        out[k] = g
    return out


# --- the draws -----------------------------------------------------------------------------------------


@dataclass
class Draw:
    cases: pd.DataFrame
    queue: pd.DataFrame
    notes: list[str] = field(default_factory=list)


def _askable(df: pd.DataFrame) -> pd.Series:
    """Commands with a real result to compare against (killed or abandoned ones are left out)."""
    return df["tool_kind"].ne("excluded") & df["output_status"].ne("missing") & df["t_call"].notna()


def _case(row: Any, case_id: str, split: str, situation: str, variant: str, seed: int, **extra: Any) -> dict[str, Any]:
    return {
        "case_id": case_id, "split": split, "situation": situation, "variant": variant, "key": row.key,
        "run_id": row.run_id, "scenario": row.scenario, "family": row.family, "agent": row.agent,
        "chain_id": None, "step": None,
        "matters": bool(row.matters), "kind": row.tool_kind,
        "shared_thing": None if pd.isna(row.shared_thing) else row.shared_thing,
        "t_ask": row.t_call, "history_keys": [], "record_keys": [], "running_keys": [], "seed": seed,
        **extra,
    }


def chain_starts(agent_rows: pd.DataFrame, length: int = CHAIN_LEN, min_matter: int = CHAIN_MIN_MATTER) -> list[int]:
    """Positions (index into ``agent_rows``) where ``length`` consecutive commands start that hold at least
    ``min_matter`` calls that matter and no excluded or unrecorded ones."""
    ok = (agent_rows["tool_kind"].ne("excluded") & agent_rows["t_call"].notna()).to_numpy()
    matter = agent_rows["matters"].to_numpy()
    out = []
    for i in range(1, len(agent_rows) - length + 1):  # i >= 1: at least one command of real past
        if ok[i:i + length].all() and matter[i:i + length].sum() >= min_matter:
            out.append(i)
    return out


def draw_cases(commands: pd.DataFrame, labels: pd.DataFrame, seed: int = DEFAULT_SEED,
               sizes: DrawSizes | None = None, queue_tools: Any = None) -> Draw:
    sizes = sizes or DrawSizes()
    df = with_labels(commands, labels)
    practice = practice_units(df, seed)
    df["split"] = ["practice" if (r, a) in practice else "test" for r, a in zip(df["run_id"], df["agent"])]
    by_agent = {k: g.sort_values("seq").reset_index(drop=True) for k, g in df.groupby(["run_id", "agent"])}
    groups = shared_groups(df)
    agent_of = dict(zip(df["key"], df["agent"]))
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    notes: list[str] = []

    def hist(r: Any, n: int = HISTORY_LEN) -> list[str]:
        return history_keys(by_agent[(r.run_id, r.agent)], r.seq, n)

    for split in ("test", "practice"):
        pool = df[df["split"] == split]
        prefix = "p-" if split == "practice" else ""
        n_shared = sizes.shared if split == "test" else sizes.practice_shared
        n_chains = sizes.chains if split == "test" else sizes.practice_chains

        # situation 3 first: it has the fewest candidates
        cands = pool[_askable(pool) & pool["matters"] & pool["shared_thing"].notna()]
        recs: dict[str, tuple[list[str], list[str]]] = {}
        keep = []
        for r in cands.itertuples(index=False):
            fin, run = record_of_others(groups[(r.run_id, r.shared_thing)], r)
            others = {agent_of[k] for k in fin + run} - {r.agent}
            if others:
                recs[r.key] = (fin, run)
                keep.append(r.key)
        cands = cands[cands["key"].isin(keep)]
        waiting = cands["shared_thing"].isin(WAITING_THINGS)
        n_wait = int(n_shared * sizes.shared_waiting_share + 0.5)
        nr_wait = int(sizes.shared_no_record * sizes.shared_waiting_share + 0.5)
        parts, no_record = [], set()
        for name, sub, n, n_nr in (("waiting", cands[waiting], n_wait, nr_wait),
                                   ("other", cands[~waiting], n_shared - n_wait, sizes.shared_no_record - nr_wait)):
            got = draw_equal(sub, n, rng_for(seed, f"{split}-shared-{name}"), cap_share=sizes.cap_share)
            parts.append(got)
            if len(got) < n:
                notes.append(f"{split}: only {len(got)} shared-tool cases on {name} things available of {n} wanted")
            if split == "test" and len(got):
                idx = rng_for(seed, f"no-record-{name}").choice(len(got), size=min(n_nr, len(got)), replace=False)
                no_record |= set(got.sort_values("key")["key"].iloc[sorted(idx)])
        shared = pd.concat(parts).sort_values("key")
        for i, r in enumerate(shared.itertuples(index=False)):
            fin, run = recs[r.key]
            cid = f"{prefix}shared-{i:04d}"
            rows.append(_case(r, cid, split, "shared", "main", seed, history_keys=hist(r), record_keys=fin, running_keys=run))
            if r.key in no_record:
                rows.append(_case(r, cid + "-norec", split, "shared", "no_record", seed, history_keys=hist(r)))
            used.add(r.key)

        # situation 2: chains, at most one per agent stretch, never overlapping a shared case
        starts = []
        for (run_id, agent), g in by_agent.items():
            if g["split"].iloc[0] != split:
                continue
            for i in chain_starts(g):
                keys = list(g["key"].iloc[i:i + CHAIN_LEN])
                if used.isdisjoint(keys):
                    starts.append({"key": g["key"].iloc[i], "family": g["family"].iloc[0], "run_id": run_id,
                                   "agent": agent, "i": i})
        starts_df = pd.DataFrame(starts, columns=["key", "family", "run_id", "agent", "i"])
        chosen = pick_chains(starts_df, n_chains, rng_for(seed, f"{split}-chains"))
        chain_steps = []
        for c_i, c in enumerate(sorted(chosen, key=lambda c: c["key"])):
            g = by_agent[(c["run_id"], c["agent"])]
            first = g.iloc[c["i"]]
            past = history_keys(g, int(first["seq"]))
            chain_id = f"{prefix}chain-{c_i:03d}"
            for s in range(CHAIN_LEN):
                r = g.iloc[c["i"] + s]
                row = _case(r, f"{chain_id}-s{s}", split, "chain", "main", seed, chain_id=chain_id, step=s,
                            history_keys=past)
                rows.append(row)
                used.add(r["key"])
                if s >= 1 and r["matters"] and r["output_status"] != "missing":
                    chain_steps.append(row)
        if len(chosen) < n_chains:
            notes.append(f"{split}: only {len(chosen)} chains available of {n_chains} wanted")
        if split == "test" and chain_steps:
            cs = pd.DataFrame(chain_steps)
            pick = draw_equal(cs, sizes.chain_real_past, rng_for(seed, "chain-real-past"))
            for r in pick.itertuples(index=False):
                src = by_agent[(r.run_id, r.agent)]
                seq = int(src.loc[src["key"] == r.key, "seq"].iloc[0])
                rows.append({**r._asdict(), "case_id": r.case_id + "-real", "variant": "real_past",
                             "history_keys": history_keys(src, seq)})

        # situation 1: single steps
        free = pool[_askable(pool) & ~pool["key"].isin(used)]
        n_matter = sizes.one_step_matter if split == "test" else sizes.practice_one_step - sizes.practice_one_step_other
        n_other = sizes.one_step_other if split == "test" else sizes.practice_one_step_other
        matter = draw_equal(free[free["matters"]], n_matter, rng_for(seed, f"{split}-one-matter"), cap_share=sizes.cap_share)
        other = draw_equal(free[~free["matters"]], n_other, rng_for(seed, f"{split}-one-other"), cap_share=sizes.cap_share)
        one = pd.concat([matter, other])
        for i, r in enumerate(one.sort_values("key").itertuples(index=False)):
            rows.append(_case(r, f"{prefix}one-{i:04d}", split, "one_step", "main", seed, history_keys=hist(r)))
            used.add(r.key)
        if len(matter) < n_matter:
            notes.append(f"{split}: only {len(matter)} one-step calls that matter of {n_matter} wanted")
        if split == "test" and len(matter):
            mains = [x for x in rows if x["situation"] == "one_step" and x["split"] == "test" and x["matters"]]
            mdf = pd.DataFrame(mains)
            longs = draw_equal(mdf, sizes.long_history, rng_for(seed, "long-history"))
            for r in longs.itertuples(index=False):
                src = by_agent[(r.run_id, r.agent)]
                seq = int(src.loc[src["key"] == r.key, "seq"].iloc[0])
                rows.append({**r._asdict(), "case_id": r.case_id + "-long", "variant": "long_history",
                             "history_keys": long_history_keys(src, seq)})
            reps = draw_equal(mdf, sizes.repeats, rng_for(seed, "repeats"))
            for r in reps.itertuples(index=False):
                rows.append({**r._asdict(), "case_id": r.case_id + "-rep", "variant": "repeat"})

    cases = pd.DataFrame(rows)
    queue = draw_queue_moments(df, seed, sizes.queue_moments, queue_tools, notes)
    return Draw(cases=cases, queue=queue, notes=notes)


def pick_chains(starts: pd.DataFrame, n: int, rng: np.random.Generator) -> list[dict[str, Any]]:
    """Choose ``n`` chain starts, an equal share per scenario, never two overlapping in one agent's
    commands. Each agent's possible starts are first packed into as many non-overlapping chains as fit
    (earliest first); the draw is then random among those, so a share can fall short only when the
    scenario really has too few."""
    if starts.empty or n <= 0:
        return []
    starts = starts.sort_values(["family", "run_id", "agent", "i"]).reset_index(drop=True)
    keep = []
    for _, g in starts.groupby(["run_id", "agent"], sort=True):
        last = -CHAIN_LEN
        for idx, i in zip(g.index, g["i"]):
            if i - last >= CHAIN_LEN:
                keep.append(idx)
                last = int(i)
    pool = starts.loc[sorted(keep)]
    target = allocate(n, pool.groupby("family").size().to_dict())
    chosen: list[dict[str, Any]] = []
    for scen in sorted(target):
        sub = pool[pool["family"] == scen]
        for j in sorted(rng.choice(len(sub), size=target[scen], replace=False)):
            chosen.append(sub.iloc[int(j)].to_dict())
    return chosen


# --- queue moments ---------------------------------------------------------------------------------------


def _queue_module() -> Any:
    try:
        from swarmbench.studies.auditor import queue_sim  # aud-yardsticks' module

        return queue_sim
    except ImportError:
        return None


def is_checker_call(command: str, queue_tools: Any = None) -> bool:
    mod = queue_tools or _queue_module()
    if mod is not None and hasattr(mod, "is_checker_call"):
        return bool(mod.is_checker_call(command))
    return bool(_CHECKER.search(command or ""))


QUEUE_TRUTH_KEYS = ["slots", "real_typical_wait_s", "real_waiting_5min", "real_waiting_10min", "real_hits_limit"]
QUEUE_SIM_KEYS = ["sim_typical_wait_s", "sim_waiting_5min", "sim_waiting_10min", "sim_hits_limit"]


def draw_queue_moments(df: pd.DataFrame, seed: int, n: int, queue_tools: Any = None,
                       notes: list[str] | None = None) -> pd.DataFrame:
    """Frozen moments of proof conference runs (test split only), at least five minutes apart, each with
    at least one proof check in flight, with ten minutes of run left after them. The real values and the
    queue program's forecast come from aud-yardsticks' queue_sim (left empty when it isn't there)."""
    mod = queue_tools or _queue_module()
    cols = ["case_id", "split", "run_id", "scenario", "t_freeze", *QUEUE_TRUTH_KEYS, *QUEUE_SIM_KEYS, "seed"]
    pc = df[df["family"].eq("proof-conference") & df["split"].eq("test")]
    if pc.empty or n <= 0:
        return pd.DataFrame(columns=cols)
    pc = pc[pc["command"].map(lambda c: is_checker_call(str(c), mod))]
    rng = rng_for(seed, "queue-moments")
    per_run: dict[str, list[pd.Timestamp]] = {}
    for run_id, g in sorted(pc.groupby("run_id"), key=lambda kv: kv[0]):
        end = df.loc[df["run_id"] == run_id, ["t_call", "t_result"]].max().max()
        start = df.loc[df["run_id"] == run_id, "t_call"].min()
        lo, hi = start + pd.Timedelta(seconds=QUEUE_GAP_S), end - pd.Timedelta(seconds=QUEUE_HORIZON_S)
        if hi <= lo:
            continue
        # candidate moments: every minute with a check in flight
        grid = pd.date_range(lo.ceil("min"), hi, freq="60s")
        busy = [t for t in grid if ((g["t_call"] <= t) & (g["t_result"].isna() | (g["t_result"] > t))).any()]
        order = rng.permutation(len(busy))
        picked: list[pd.Timestamp] = []
        for i in order:
            t = busy[int(i)]
            if all(abs((t - p).total_seconds()) >= QUEUE_GAP_S for p in picked):
                picked.append(t)
        per_run[run_id] = sorted(picked)
    alloc = allocate(n, {r: len(v) for r, v in per_run.items()})
    rows = []
    problems: list[str] = []
    for run_id in sorted(alloc):
        times = per_run[run_id]
        idx = sorted(rng.choice(len(times), size=alloc[run_id], replace=False))
        for i in idx:
            t = times[int(i)]
            row: dict[str, Any] = {"run_id": run_id, "scenario": str(pc.loc[pc["run_id"] == run_id, "scenario"].iloc[0]),
                                   "t_freeze": t, "split": "test", "seed": seed}
            values, problem = _queue_values(mod, run_id, t)
            row.update(values)
            if problem and problem not in problems:
                problems.append(problem)
            rows.append(row)
    out = pd.DataFrame(rows, columns=[c for c in cols if c != "case_id"])
    out = out.sort_values(["run_id", "t_freeze"]).reset_index(drop=True)
    out.insert(0, "case_id", [f"queue-{i:03d}" for i in range(len(out))])
    if notes is not None:
        notes.extend(problems)
    return out[cols]


def _queue_values(mod: Any, run_id: str, t: pd.Timestamp) -> tuple[dict[str, Any], str | None]:
    """(the real values and the queue program's forecast, or why they are missing). A run the queue
    program can't read (its folder or files missing) gets empty values, never a failed draw."""
    out: dict[str, Any] = {k: None for k in QUEUE_TRUTH_KEYS + QUEUE_SIM_KEYS}
    if mod is None:
        return out, "queue values empty: the queue program (queue_sim) is not available"
    try:
        if hasattr(mod, "queue_truth"):
            out.update({k: v for k, v in (mod.queue_truth(run_id, t) or {}).items() if k in out})
        if hasattr(mod, "queue_forecast"):
            out.update({k: v for k, v in (mod.queue_forecast(run_id, t) or {}).items() if k in out})
    except Exception as exc:  # any failure leaves this run's values empty, with a note
        return {k: None for k in out}, f"queue values empty for {run_id}: {type(exc).__name__}: {str(exc)[:200]}"
    return out, None


# --- saving ---------------------------------------------------------------------------------------------


def save(draw: Draw, data_dir: Path = DATA_DIR, meta: dict[str, Any] | None = None) -> dict[str, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    paths = {"cases": data_dir / "cases.parquet", "queue": data_dir / "queue_cases.parquet",
             "meta": data_dir / "cases_meta.json"}
    did = draw_id(draw)
    draw.cases["draw_id"] = did
    draw.queue["draw_id"] = did
    draw.cases.to_parquet(paths["cases"], index=False)
    draw.queue.to_parquet(paths["queue"], index=False)
    paths["meta"].write_text(json.dumps({**(meta or {}), "draw_id": did, "notes": draw.notes,
                                         "draw_version": DRAW_VERSION}, indent=2, default=str))
    return paths


def draw_id(draw: Draw) -> str:
    """A short hash of what was drawn (which command each case asks about, and what it shows). Every
    answer line carries it, so answers can't silently be scored against a different draw."""
    h = hashlib.sha256()
    for r in draw.cases.sort_values("case_id").itertuples(index=False):
        h.update(json.dumps([r.case_id, r.key, r.variant, list(r.history_keys), list(r.record_keys),
                             list(r.running_keys)]).encode())
    for r in draw.queue.sort_values("case_id").itertuples(index=False):
        h.update(json.dumps([r.case_id, r.run_id, str(r.t_freeze)]).encode())
    return h.hexdigest()[:12]


def load_cases(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    cases = pd.read_parquet(data_dir / "cases.parquet")
    qpath = data_dir / "queue_cases.parquet"
    queue = pd.read_parquet(qpath) if qpath.exists() else pd.DataFrame()
    for col in ("history_keys", "record_keys", "running_keys"):
        cases[col] = cases[col].map(lambda v: list(v) if v is not None else [])
    return cases, queue


def summary(draw: Draw) -> str:
    c = draw.cases
    if c.empty:
        return "no cases drawn"
    lines = ["asks by split, situation and variant:"]
    for (split, sit, var), n in c.groupby(["split", "situation", "variant"]).size().items():
        lines.append(f"  {split:8s} {sit:9s} {var:13s} {n}")
    lines.append("asks by scenario (test, main):")
    main = c[(c["split"] == "test") & (c["variant"] == "main")]
    for (scen, sit), n in main.groupby(["family", "situation"]).size().items():
        lines.append(f"  {scen:28s} {sit:9s} {n}")
    lines.append(f"queue moments: {len(draw.queue)}")
    lines += [f"note: {n}" for n in draw.notes]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Draw the auditor study's cases (no model calls).")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--commands", type=Path, default=None, help="commands table (default: full, else sample)")
    ap.add_argument("--labels", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=DATA_DIR)
    args = ap.parse_args(argv)
    cpath = args.commands or commands_path()
    commands = load_commands(cpath)
    labels, source = load_labels(commands, args.labels)
    draw = draw_cases(commands, labels, args.seed)
    paths = save(draw, args.out, {"seed": args.seed, "commands": str(cpath), "labels": source,
                                  "sizes": asdict(DrawSizes())})
    print(summary(draw))
    print(f"labels from: {source}")
    print("saved:", ", ".join(str(p) for p in paths.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
