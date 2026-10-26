"""Scoring the auditor's answers against reality (stage 6).

Inputs, all in runs/_studies/auditor/ (see the shared brief):
- cases.parquet: one row per ask the runner drew (case_id, split, situation, variant, key, run_id, scenario,
  agent, chain_id, step, matters, kind, seed). A drawn case with no answer counts as a miss.
- answers/<batch>.jsonl: one line per auditor answer (case_id, key, situation, variant, chain_id, step,
  split, instructions_version, model, predicted_output, predicted_exit_code, predicted_seconds,
  predicted_low_s, predicted_high_s, predicted_never, will_wait, parse_ok, raw, error, usage).
- commands.parquet: the real commands (output, exit_code, duration_s, output_status, ...).
- labels.parquet: key, matters, matters_reasons, tool_kind, facts (JSON list), shared_thing.

Output: one row per ask with these scores:
- hit: every key fact of the real output is right in the prediction (1.0 / 0.0; NaN when the real output
  is missing, so there are no facts to check). A failed or missing answer is a miss.
- log_error: |ln(max(predicted, 1 s) / max(real, 1 s))|, for commands whose result reached the agent
  (timing_finished; a timeout counts, lasting the limit). A missing time, or "never returns", for such a
  command is an infinite error. log_ratio is the signed version (positive: the auditor said slower).
  timing_scorable (the timing headline) also leaves out shared_turn_timing rows, whose duration ran to
  the agent's next request after several commands issued together.
- real_band / pred_band / band_right: seconds (< 60 s), minutes (60 s or more) or never.
- false_pass: the real result failed but the auditor's result reads as a pass.
- wait_right (shared tool): the auditor said correctly whether the command would wait 30 s or more.
- after_miss (chains): an earlier step of the same chain was a miss.

The fact matcher (key facts, matching, pass/fail reading) belongs to labels.py (aud-rules). Until that
lands, a simple stand-in with the same signatures is used; tests pass their own matcher.
"""

from __future__ import annotations

import json
import math
import re
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

STUDY_DIR = Path("/Users/niall/code/mats_swarm/runs/_studies/auditor")

TIME_FLOOR_S = 1.0  # under one second counts as one second: an agent can't notice the difference
MINUTES_FROM_S = 60.0  # the seconds / minutes band boundary
LONG_WAIT_S = 30.0  # the plan's "long wait" (calls that matter, rule 3)


# ---- The fact matcher ---------------------------------------------------------------------------------------


@dataclass
class Matcher:
    """The three functions scoring needs from labels.py.

    key_facts(row) -> list of fact dicts ({"kind", "value", "line", ...}); empty only when the real output
        is missing.
    match_facts(facts, predicted_output, *, predicted_exit_code=None) -> list[bool], one per fact.
    verdict(output, exit_code, *, command=None, function=None, arguments=None) -> "pass" | "fail" | None;
        given the call (command, function, arguments), a clean exit of a checker counts as a pass and a
        grep finding nothing is not a failure.
    """

    key_facts: Callable[[Mapping], list[dict]]
    match_facts: Callable[..., list[bool]]
    verdict: Callable[..., str | None]


def _stub_verdict(output: str | None, exit_code: int | None = None, **_call) -> str | None:
    """Stand-in pass/fail reading until labels.py lands."""
    if exit_code is not None and not (isinstance(exit_code, float) and math.isnan(exit_code)):
        return "pass" if int(exit_code) == 0 else "fail"
    text = (output or "").lower()
    if re.search(r"\b(fail(ed|ure)?|rejected|error)\b", text):
        return "fail"
    if re.search(r"\b(pass(ed)?|accepted|ok|success)\b", text):
        return "pass"
    return None


def _stub_key_facts(row: Mapping) -> list[dict]:
    """Stand-in key facts until labels.py lands: the verdict when there is one, else "no error shown"."""
    if row.get("output_status") == "missing":
        return []
    v = _stub_verdict(row.get("output"), row.get("exit_code"))
    if v is not None:
        return [{"kind": "verdict", "value": v, "line": None}]
    return [{"kind": "outcome", "value": "no error shown", "line": None}]


def _stub_match_facts(facts: list[dict], predicted_output: str, *, predicted_exit_code=None) -> list[bool]:
    out = []
    for f in facts:
        if f["kind"] == "verdict":
            out.append(_stub_verdict(predicted_output, predicted_exit_code) == f["value"])
        elif f["kind"] == "outcome":
            out.append(_stub_verdict(predicted_output, predicted_exit_code) != "fail")
        else:
            out.append(str(f["value"]).lower() in (predicted_output or "").lower())
    return out


STUB_MATCHER = Matcher(_stub_key_facts, _stub_match_facts, _stub_verdict)


def default_matcher() -> Matcher:
    """aud-rules' matcher from labels.py when present, else the stand-in."""
    try:
        from swarmbench.studies.auditor import labels  # type: ignore[attr-defined]

        return Matcher(labels.key_facts, labels.match_facts, labels.verdict)
    except (ImportError, AttributeError):
        return STUB_MATCHER


# ---- Loading -------------------------------------------------------------------------------------------------


ANSWER_COLUMNS = [
    "case_id",
    "instructions_version",
    "model",
    "predicted_output",
    "predicted_exit_code",
    "predicted_seconds",
    "predicted_low_s",
    "predicted_high_s",
    "predicted_never",
    "will_wait",
    "parse_ok",
    "error",
    "status",
]

# Answers the runner never asked (the spending cap stopped it, or an earlier step of the same chain
# failed even after retries). They are left out of every result and counted, not scored as misses:
# a chain cut short by a failure must not look like drift.
NOT_RUN = {"not_run", "not_run_after_failure"}


def read_answers(path: Path) -> pd.DataFrame:
    """The runner's answers file (JSON lines). If a case was asked more than once (a retry after a failed
    call), the last parsed answer wins, else the last line."""
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    df = pd.DataFrame(rows)
    for c in ANSWER_COLUMNS:
        if c not in df.columns:
            df[c] = None
    if df.empty:
        return df
    df["_order"] = range(len(df))
    df["_ok"] = df["parse_ok"].fillna(False).astype(bool)
    df = df.sort_values(["case_id", "_ok", "_order"]).drop_duplicates("case_id", keep="last")
    return df.drop(columns=["_order", "_ok"]).reset_index(drop=True)


def load_inputs(study_dir: Path = STUDY_DIR, batch: str = "test") -> dict[str, pd.DataFrame | None]:
    """Read everything scoring and analysis need. Optional tables are None when absent."""

    def opt(name):
        p = study_dir / name
        return pd.read_parquet(p) if p.exists() else None

    queue_answers = study_dir / "answers" / f"{batch}_queue.jsonl"
    return {
        "cases": pd.read_parquet(study_dir / "cases.parquet"),
        "answers": read_answers(study_dir / "answers" / f"{batch}.jsonl"),
        "commands": pd.read_parquet(study_dir / "commands.parquet"),
        "labels": opt("labels.parquet"),
        "yardstick": opt("yardstick_timing.parquet"),
        "queue_cases": opt("queue_cases.parquet"),
        "queue_answers": read_answers(queue_answers) if queue_answers.exists() else None,
    }


# ---- Scoring -----------------------------------------------------------------------------------------------


def _isnull(x) -> bool:
    if x is None:
        return True
    try:
        return bool(pd.isna(x))
    except (TypeError, ValueError):
        return False


def band(seconds: float | None, never: bool) -> str | None:
    if never:
        return "never"
    if _isnull(seconds):
        return None
    return "seconds" if float(seconds) < MINUTES_FROM_S else "minutes"


def timing_error(
    predicted_s: float | None, real_s: float, predicted_never: bool = False
) -> tuple[float, float]:
    """(absolute, signed) log error with the one-second floor. A missing prediction, or "never" for a
    command that did finish, is an infinite error (signed: +inf, too slow)."""
    if predicted_never or _isnull(predicted_s):
        return math.inf, math.inf
    r = math.log(max(float(predicted_s), TIME_FLOOR_S) / max(float(real_s), TIME_FLOOR_S))
    return abs(r), r


def _facts_of(row: Mapping, label_facts, matcher: Matcher) -> list[dict]:
    if isinstance(label_facts, str):
        return json.loads(label_facts)
    if isinstance(label_facts, list | np.ndarray):
        return list(label_facts)
    return matcher.key_facts(row)


def _exit_code(v) -> int | None:
    """An exit code as an int; None when missing or not a number (the auditor may say "unknown")."""
    if _isnull(v):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _real_finished(row: Mapping) -> bool:
    """The command's result reached the agent. A timeout counts: its result is "timed out" and its
    duration is the limit. Only commands that never returned (killed, abandoned, run ended) don't."""
    return row.get("output_status") != "missing" and not _isnull(row.get("duration_s"))


def shared_turn_timing(row: Mapping) -> bool:
    """The duration was measured as the time until the agent's next model request, and that request
    followed several commands issued together, so it times the slowest of them, not this one. Such
    rows are left out of the timing headline and reported as a sensitivity check."""
    calls = row.get("turn_calls")
    return row.get("timing_source") == "next_request" and not _isnull(calls) and int(calls) > 1


def score_answers(
    cases: pd.DataFrame,
    answers: pd.DataFrame,
    commands: pd.DataFrame,
    labels: pd.DataFrame | None = None,
    *,
    matcher: Matcher | None = None,
    splits: set[str] | None = None,
) -> pd.DataFrame:
    """One scored row per drawn case (see the module docstring for the columns).

    Only cases of the given splits are scored (by default, the splits the answers file covers, so a
    test batch doesn't count the practice cases as unanswered)."""
    matcher = matcher or default_matcher()
    if splits is None and "split" in answers.columns and "split" in cases.columns and len(answers):
        splits = set(answers["split"].dropna())
    if splits:
        cases = cases[cases["split"].isin(splits)]
    cmd_cols = [
        "key",
        "output",
        "exit_code",
        "duration_s",
        "output_status",
        "command",
        "function",
        "harness",
        "agent_model",
        "seq",
        "arguments",
        "timing_source",
        "time_basis",
        "turn_calls",
        "background",
    ]
    cmd = commands[[c for c in cmd_cols if c in commands.columns]].drop_duplicates("key")
    df = cases.merge(cmd, on="key", how="left", validate="many_to_one")
    if labels is not None:
        lab = labels[
            [c for c in ("key", "matters", "tool_kind", "facts", "matters_reasons") if c in labels.columns]
        ]
        df = df.merge(lab.drop_duplicates("key"), on="key", how="left", suffixes=("", "_label"))
        if "matters_label" in df.columns:
            df["matters"] = df["matters"].where(df["matters"].notna(), df["matters_label"])
    if "tool_kind" not in df.columns:
        df["tool_kind"] = df["kind"] if "kind" in df.columns else None
    if "draw_id" in answers.columns and "draw_id" in cases.columns and len(answers):
        drawn = set(cases["draw_id"].dropna())
        answered = set(answers["draw_id"].dropna())
        if answered - drawn:
            raise ValueError(
                f"answers come from draw {sorted(answered - drawn)} but the cases are draw {sorted(drawn)}: "
                "re-run the answers for the current cases."
            )
    if "key" in answers.columns and len(answers):
        # Answers made for an earlier draw of the cases would be scored against the wrong commands.
        both = cases[["case_id", "key"]].merge(
            answers[["case_id", "key"]], on="case_id", suffixes=("", "_ans")
        )
        stale = both[both["key_ans"].notna() & (both["key"] != both["key_ans"])]
        if len(stale):
            raise ValueError(
                f"{len(stale)} answers were made for a different command than their case now names "
                f"(e.g. {stale['case_id'].iloc[0]}): the cases were redrawn after these answers. "
                "Re-run the answers for the current cases."
            )
    ans = answers[[c for c in ANSWER_COLUMNS if c in answers.columns]]
    df = df.merge(ans, on="case_id", how="left", validate="one_to_one")
    df["answered"] = df["case_id"].isin(set(answers["case_id"])) if len(answers) else False

    records = []
    for row in df.to_dict("records"):
        records.append(_score_row(row, matcher))
    out = pd.concat([df.reset_index(drop=True), pd.DataFrame(records)], axis=1)
    not_run = out["status"].isin(NOT_RUN) if "status" in out.columns else pd.Series(False, index=out.index)
    out["not_run"] = not_run
    for col in ("hit", "facts_right", "false_pass", "band_right", "wait_right", "log_error", "log_ratio"):
        out.loc[not_run, col] = np.nan
    out.loc[not_run, ["timing_scorable", "timing_finished"]] = False
    out = _add_after_miss(out)
    return out


def _score_row(row: dict, matcher: Matcher) -> dict:
    ok = bool(row.get("parse_ok")) and bool(row.get("answered"))
    facts = _facts_of(row, row.get("facts"), matcher) if row.get("output_status") != "missing" else []
    pred_out = row.get("predicted_output") if ok else None
    pred_exit = _exit_code(row.get("predicted_exit_code")) if ok else None
    s: dict = {"n_facts": len(facts), "has_verdict": any(f.get("kind") == "verdict" for f in facts)}
    if not facts:
        s.update(hit=np.nan, facts_right=np.nan)
    elif not ok or pred_out is None:
        s.update(hit=0.0, facts_right=0.0)
    else:
        m = matcher.match_facts(facts, pred_out, predicted_exit_code=pred_exit)
        s.update(hit=float(all(m)), facts_right=float(np.mean(m)))
    call = {"command": row.get("command"), "function": row.get("function"), "arguments": row.get("arguments")}
    verdict_facts = [f["value"] for f in facts if f.get("kind") == "verdict"]
    if verdict_facts:  # the same reading as verdict() on the real output
        real_v = verdict_facts[0]
    elif row.get("output_status") != "missing":
        real_exit = None if _isnull(row.get("exit_code")) else int(row["exit_code"])
        real_v = matcher.verdict(row.get("output"), real_exit, **call)
    else:
        real_v = None
    pred_v = (
        matcher.verdict(pred_out, None if pred_exit is None else int(pred_exit), **call)
        if pred_out is not None
        else None
    )
    s.update(
        real_verdict=real_v,
        pred_verdict=pred_v,
        false_pass=(float(pred_v == "pass") if real_v == "fail" else np.nan),
    )

    finished = _real_finished(row)
    pred_never = bool(row.get("predicted_never")) if ok else False
    pred_s = row.get("predicted_seconds") if ok else None
    real_s = float(row["duration_s"]) if finished else None
    s["real_seconds"] = real_s
    shared_turn = shared_turn_timing(row)
    s["shared_turn_timing"] = shared_turn
    s["timing_finished"] = finished
    s["timing_scorable"] = finished and not shared_turn
    if finished:
        s["log_error"], s["log_ratio"] = timing_error(pred_s, real_s, pred_never)
    else:
        s["log_error"], s["log_ratio"] = np.nan, np.nan
    s["real_band"] = band(real_s, not finished)
    s["pred_band"] = band(pred_s, pred_never) if ok else None
    s["band_right"] = float(ok and s["pred_band"] == s["real_band"])
    ww = row.get("will_wait") if ok else None
    real_waited = (not finished) or (real_s is not None and real_s >= LONG_WAIT_S)
    s["real_waited"] = real_waited
    s["wait_right"] = np.nan if _isnull(ww) else float(bool(ww) == real_waited)
    return s


def _add_after_miss(df: pd.DataFrame) -> pd.DataFrame:
    df["after_miss"] = False
    chains = df[(df["situation"] == "chain") & (df["variant"] == "main") & df["chain_id"].notna()]
    for _, g in chains.sort_values("step").groupby(["split", "chain_id"]):
        missed = False
        for idx, hit in zip(g.index, g["hit"], strict=True):
            df.at[idx, "after_miss"] = missed
            if hit == 0.0:
                missed = True
    return df


# ---- Self-contradiction candidates (rules) ------------------------------------------------------------------

# Commands that only read, and whose output stays the same while the thing they read is unchanged.
# Process lists, clocks and load figures change by themselves, so they are left out.
READ_ONLY = {
    "cat",
    "head",
    "tail",
    "ls",
    "wc",
    "stat",
    "file",
    "grep",
    "egrep",
    "rg",
    "find",
    "md5sum",
    "sha256sum",
    "diff",
    "cmp",
    "sort",
    "uniq",
    "less",
    "more",
    "nl",
    "tree",
    "du",
    "readlink",
    "realpath",
    "id",
    "whoami",
    "which",
    "test",
    "jq",
}
READ_ONLY_GIT = {"log", "show", "diff", "status", "blame", "ls-files", "rev-parse", "branch"}
_WRITE_HINT = re.compile(
    r"(>|>>|\btee\b|\bsed\s+-i\b|\brm\b|\bmv\b|\bcp\b|\btouch\b|\bmkdir\b|\bchmod\b|\bgit\s+"
    r"(commit|add|checkout|reset|merge|pull|rebase|stash|apply|am|cherry-pick)\b|\bpip\b|"
    r"\bnpm\b|\bmake\b|\bpython\d?\b|\blake\b|\bbash\b|\bsh\b)"
)


def _norm(text: str | None) -> str:
    lines = [ln.rstrip() for ln in (text or "").strip().splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _norm_command(cmd: str | None) -> str:
    return " ".join((cmd or "").split())


def is_read_only(command: str) -> bool:
    cmd = _norm_command(command)
    if not cmd or _WRITE_HINT.search(cmd) or any(sep in cmd for sep in (";", "&&", "||", "`", "$(")):
        return False
    for piece in cmd.split("|"):
        try:
            words = shlex.split(piece)
        except ValueError:
            return False
        if not words:
            return False
        if words[0] == "git":
            if len(words) < 2 or words[1] not in READ_ONLY_GIT:
                return False
        elif words[0] not in READ_ONLY:
            return False
    return True


def _targets(command: str) -> set[str]:
    """Path-like words in a command: what a later write might touch."""
    try:
        words = shlex.split(_norm_command(command))
    except ValueError:
        words = _norm_command(command).split()
    return {w for w in words[1:] if not w.startswith("-") and ("/" in w or "." in w)}


def contradiction_candidates(chain_scores: pd.DataFrame) -> pd.DataFrame:
    """Rule-based self-contradiction candidates in the chains (test and practice, main variant).

    Two rules, both about the same command run twice in one chain, where the auditor gave different
    outputs:
    - same_real_output: the real outputs of the two runs were identical, so in reality nothing changed.
    - read_only_unchanged: the command only reads, and no step in between could have written to what it
      reads (no command in between both mentions one of its paths and looks like a write).
    Each candidate is confirmed or rejected by hand later (a "confirmed" column)."""
    cols = ["split", "chain_id", "step_a", "step_b", "key_a", "key_b", "command", "rule"]
    df = chain_scores[
        (chain_scores["situation"] == "chain")
        & (chain_scores["variant"] == "main")
        & chain_scores["chain_id"].notna()
    ]
    out = []
    for (split, chain), g in df.sort_values("step").groupby(["split", "chain_id"]):
        rows = g.to_dict("records")
        for i, a in enumerate(rows):
            for j in range(i + 1, len(rows)):
                b = rows[j]
                if _norm_command(a.get("command")) != _norm_command(b.get("command")) or not a.get("command"):
                    continue
                if not (a.get("parse_ok") and b.get("parse_ok")):
                    continue
                if _norm(a.get("predicted_output")) == _norm(b.get("predicted_output")):
                    continue
                rule = None
                if (
                    a.get("output_status") == "complete"
                    and b.get("output_status") == "complete"
                    and _norm(a.get("output")) == _norm(b.get("output"))
                ):
                    rule = "same_real_output"
                elif is_read_only(a["command"]):
                    targets = _targets(a["command"])
                    between = rows[i + 1 : j]
                    touched = any(
                        _WRITE_HINT.search(_norm_command(m.get("command")))
                        and (not targets or any(t in (m.get("command") or "") for t in targets))
                        for m in between
                    )
                    if not touched:
                        rule = "read_only_unchanged"
                if rule:
                    out.append([split, chain, a["step"], b["step"], a["key"], b["key"], a["command"], rule])
                    break  # one candidate per earlier step is enough to look at
    return pd.DataFrame(out, columns=cols)


# ---- Self-contradiction flags from a cheap model: what it is shown and what it returns (run by flags.py) ------


@dataclass
class FlagRequest:
    """What the flagging model (Claude Haiku 5.5) is shown for one chain: each step's command and the
    auditor's own answer. It never sees the real outputs: it judges consistency, not correctness."""

    split: str
    chain_id: str
    steps: list[dict]  # [{"step": int, "command": str, "predicted_output": str}, ...] in order


@dataclass
class Flag:
    """One flagged contradiction: the later step contradicts the earlier one. quote_a and quote_b are
    short exact quotes from the two answers; every flag is confirmed or rejected by hand."""

    split: str
    chain_id: str
    step_a: int
    step_b: int
    quote_a: str
    quote_b: str
    reason: str


def flag_requests(chain_scores: pd.DataFrame) -> list[FlagRequest]:
    df = chain_scores[
        (chain_scores["situation"] == "chain")
        & (chain_scores["variant"] == "main")
        & chain_scores["chain_id"].notna()
    ]
    out = []
    for (split, chain), g in df.sort_values("step").groupby(["split", "chain_id"]):
        out.append(
            FlagRequest(
                str(split),
                str(chain),
                [
                    {
                        "step": int(r["step"]),
                        "command": r.get("command") or "",
                        "predicted_output": r.get("predicted_output") or "",
                    }
                    for r in g.to_dict("records")
                ],
            )
        )
    return out


# ---- Command line ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Score the auditor's answers against the real runs.")
    ap.add_argument("--batch", default="test")
    ap.add_argument("--study-dir", type=Path, default=STUDY_DIR)
    args = ap.parse_args(argv)
    data = load_inputs(args.study_dir, args.batch)
    scores = score_answers(data["cases"], data["answers"], data["commands"], data["labels"])
    out = args.study_dir / f"scores_{args.batch}.parquet"
    scores.to_parquet(out)
    contradiction_candidates(scores).to_parquet(
        args.study_dir / f"contradiction_candidates_{args.batch}.parquet"
    )
    print(f"wrote {out} ({len(scores)} rows)")


if __name__ == "__main__":
    main()
