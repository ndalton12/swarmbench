"""The agent-reaction test: do the auditor's mistakes change what the agent does next?

The auditor study (``runner.py``, ``score.py``) asked AI models to pretend to be the machine and predict
what a real tool call printed. On calls that matter they got every key fact right about half the time.
This test asks whether the misses matter: had the agent seen the auditor's output instead of the real
one, would it have done something different next?

For each case (one real tool call and one auditor's prediction of its output) the agent's next model
request is rebuilt twice and sent to the agent's own model, with the logged call's tools, tool choice and
generation settings:

- **A**: the request with the auditor's predicted output in place of the real one (same wrapper, exit
  code line from the prediction; ``reaction_inputs`` has the rules per harness);
- **R**: the logged request unchanged (a fresh sample, to measure how much the model varies anyway).

**L** is what the agent really did next (the logged answer). The three next actions are read and
compared by fixed rules (``reaction_actions``, whose docstring states them). The measures:

- P(A≠L) and P(R≠L), overall, for misses and hits apart, and by kind of wrong fact;
- **the main result: the excess change rate on misses**, P(A≠L) − P(R≠L), computed per case and
  averaged (paired), with a 95% cluster-bootstrap range (runs redrawn within scenario families, agents
  within runs; the auditor study's scheme);
- P(A≠R).

The sample (``sample``)
-----------------------

About 100 cases, seed 20261027, from the three auditors' test answers (Opus 5.5, Gemini 4 Argon,
GPT-6.1 Sol) in the one-step and shared-tool situations (their main variant: the real past, and the
record of the others for the shared tool), where everything before the call is real. Only calls that
matter, answers given and readable, not refused, whose real output is complete; not commands still
running in the background (except Antigravity's, whose finish notice is swapped), not Codex calls other
than ``exec``, not answers saying no result ever comes back, and only agent models that can still be
called (on OpenRouter's current list).

- **75 misses**, stratified by the kind of the first wrong key fact (in the order the fact matcher lists
  them): verdict (pass or fail; also "no error" shown as an error), other agents' activity, timeout or
  wait (a time-out, lock, busy or queue fact or error), error detail (the first error, file names),
  counts and numbers. Equal shares, what a kind can't give shared among the others.
- **25 hits** as controls.
- Each command is used once, with one auditor's answer. Picks are made one at a time; each takes the
  eligible answer whose auditor (within its kind), run, harness and agent model have been picked least
  so far, a seeded random number breaking ties; no run gives more than 6 cases, so the 30-agent proof
  conference runs don't dominate.
- A case whose request can't be rebuilt faithfully (``build``) is recorded in ``unbuildable.json``;
  drawing again leaves it out and picks a replacement the same way.

Steps
-----

``uv run python -m swarmbench.studies.auditor.reaction <step>``:

- ``sample``: draw the cases (``sample.parquet``, ``sample_summary.txt``, ``left_out.csv``);
- ``build``: rebuild every case's A and R requests from the run logs, one log at a time, and check them
  (``inputs/<case>.json.gz`` holds exactly what is sent, ``inputs/<case>_target.txt`` the one message
  that differs; ``build.parquet``, ``build_summary.txt``);
- ``project``: the projected cost of the real run, by agent model;
- ``run --dry-run --cap X``: the whole run with Inspect's mock model (free); ``run --live --cap X``: the
  real run, only after the user approves the cap;
- ``score --batch B`` and ``report --batch B``: the actions and the measures (``scores_<B>.parquet``,
  ``results_<B>.json``, ``report_<B>.txt``).

Everything is written to ``runs/_studies/auditor_general/reaction/`` in the main checkout.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from swarmbench.studies.auditor.cases import DATA_DIR, RUNS_DIR, allocate, rng_for, scenario_family

SEED = 20261027
OUT_DIR = RUNS_DIR / "_studies" / "auditor_general" / "reaction"
AUDITORS = {
    "anthropic/claude-opus-5-5": "scores_test.parquet",
    "openrouter/google/gemini-4-argon": "scores_test-gemini-4-argon.parquet",
    "openai/gpt-6.1-sol": "scores_test-gpt-6.1-sol.parquet",
}
SITUATIONS = ("one_step", "shared")
N_MISSES = 75
N_HITS = 25
RUN_CAP = 6
KINDS = ("verdict", "others", "wait", "error", "counts")
KIND_NAMES = {
    "verdict": "verdict (pass or fail)",
    "others": "other agents' activity",
    "wait": "timeout or wait",
    "error": "error detail",
    "counts": "counts and numbers",
}
WAIT_FAMILIES = {"timeout", "busy", "would_block", "git:locked"}
WAIT_PHRASES = {"timeout", "locked", "busy", "queued"}


def fact_kind(fact: dict[str, Any]) -> str:
    """The kind of one key fact (the sample is stratified by the kind of the first wrong one)."""
    kind, sub = fact.get("kind"), fact.get("sub")
    if kind in ("verdict", "outcome"):
        return "verdict"
    if kind == "error":
        return "wait" if fact.get("family") in WAIT_FAMILIES else "error"
    if sub in ("activity", "account"):
        return "others"
    if sub == "phrase":
        return "wait" if fact.get("value") in WAIT_PHRASES else "error"
    if sub in ("count", "number"):
        return "counts"
    return "error"  # names in errors and in git status


# --- the sample --------------------------------------------------------------------------------------------


def model_callable(model: str) -> bool:
    """Whether an agent model can still be called: it is on OpenRouter's current model list (saved by
    ``swarmbench.pricing``; models called directly through Anthropic or OpenAI are looked up there too, as
    a sign the provider still serves them). Checking costs nothing: no model is called."""
    from swarmbench import pricing

    return pricing.load().lookup(model) is not None


def _na(v: Any) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def candidates(data_dir: Path = DATA_DIR, callable_fn: Any = model_callable,
               unbuildable: list[dict[str, Any]] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every answer that could be a case, and the ones left out with the reason.

    Kept: the three auditors' test answers in the one-step and shared-tool situations (main variant: the
    real past, the record of the others where the situation has one), on calls that matter, answered
    and readable, not refused, whose real output is complete. Answers an earlier ``build`` could not
    rebuild (``unbuildable``) are left out too."""
    cannot = {(u["auditor"], u["key"]): u["reason"] for u in unbuildable or []}
    from swarmbench.studies.auditor import labels

    cmd_cols = ["key", "call_event", "result_event", "log_file", "task_id", "seq", "t_call"]
    commands = pd.read_parquet(data_dir / "commands.parquet", columns=cmd_cols)
    keep, dropped = [], []
    callable_cache: dict[str, bool] = {}
    for auditor, fname in AUDITORS.items():
        s = pd.read_parquet(data_dir / fname)
        s = s[s["situation"].isin(SITUATIONS) & (s["variant"] == "main") & (s["split"] == "test")]
        s = s[s["matters"].fillna(False).astype(bool)]
        for r in s.to_dict("records"):
            why = None
            refused = bool(r.get("refused")) if not _na(r.get("refused")) else False
            if r.get("status") != "answered" or not bool(r.get("parse_ok")):
                why = "not answered or unreadable"
            elif refused or r.get("stop_reason") == "content_filter":
                why = "refused"
            elif r.get("output_status") != "complete" or _na(r.get("hit")):
                why = "real output not complete"
            elif (auditor, r["key"]) in cannot:
                why = f"could not be rebuilt: {cannot[(auditor, r['key'])]}"
            elif bool(r.get("predicted_never")):
                why = "the auditor said no result ever comes back (nothing to put in its place)"
            elif bool(r.get("background")) and r.get("harness") != "antigravity":
                why = "background command (only Antigravity's finish notices are swapped)"
            elif r.get("harness") == "codex" and r.get("function") != "exec":
                why = "Codex call that is not exec"
            else:
                model = str(r.get("agent_model"))
                if model not in callable_cache:
                    callable_cache[model] = bool(callable_fn(model))
                if not callable_cache[model]:
                    why = f"agent model {model} can't be called any more"
            base = {"auditor": auditor, "source_case_id": r["case_id"], "key": r["key"], "run_id": r["run_id"],
                    "agent_model": r.get("agent_model"), "harness": r.get("harness")}
            if why:
                dropped.append({**base, "reason": why})
                continue
            facts = json.loads(r["facts"]) if isinstance(r["facts"], str) else list(r["facts"])
            pred_exit = None if _na(r.get("predicted_exit_code")) else int(r["predicted_exit_code"])
            ok = labels.match_facts(facts, r.get("predicted_output"), predicted_exit_code=pred_exit)
            wrong = [f for f, good in zip(facts, ok, strict=True) if not good]
            keep.append({
                **base,
                "scenario": r.get("scenario"),
                "family": scenario_family(r.get("scenario")),
                "agent": r.get("agent"),
                "function": r.get("function"),
                "situation": r.get("situation"),
                "hit": float(r["hit"]),
                "n_facts": len(facts),
                "miss_kind": fact_kind(wrong[0]) if wrong else None,
                "wrong_kinds": ",".join(sorted({fact_kind(f) for f in wrong})),
                "first_wrong_fact": json.dumps(wrong[0], default=str) if wrong else None,
                "facts": json.dumps(facts, default=str),
                "predicted_output": r.get("predicted_output") or "",
                "predicted_exit_code": pred_exit,
                "output": r.get("output"),
                "exit_code": None if _na(r.get("exit_code")) else int(r["exit_code"]),
                "command": r.get("command"),
                "arguments": r.get("arguments"),
                "background": bool(r.get("background")),
                "turn_calls": int(r.get("turn_calls") or 1),
                "real_verdict": r.get("real_verdict"),
                "pred_verdict": None if _na(r.get("pred_verdict")) else r.get("pred_verdict"),
            })
    if not keep:
        return pd.DataFrame(columns=["auditor", "key", "run_id", "hit", "miss_kind"]), pd.DataFrame(dropped)
    cands = pd.DataFrame(keep).merge(commands, on="key", how="left", validate="many_to_one")
    missing = cands["result_event"].isna() | cands["call_event"].isna()
    for r in cands[missing].to_dict("records"):
        dropped.append({k: r[k] for k in ("auditor", "source_case_id", "key", "run_id", "agent_model", "harness")}
                       | {"reason": "no next model call recorded"})
    return cands[~missing].reset_index(drop=True), pd.DataFrame(dropped)


def _pick(pool: pd.DataFrame, n: int, taken: set[str], run_count: Counter,
          criteria: list[tuple[str, Counter]], rand: dict[str, float]) -> list[int]:
    """Pick ``n`` rows one at a time. Each pick is the eligible row (its command not taken yet, its run
    under the cap) that is least represented so far by the criteria, in order of importance: each
    criterion is a column and the counter of how often each of its values has been picked. A seeded
    random number breaks ties."""
    out: list[int] = []
    for _ in range(n):
        best, best_score = None, None
        for idx, r in pool.iterrows():
            if r["key"] in taken or run_count[r["run_id"]] >= RUN_CAP:
                continue
            score = tuple(counter[r[col]] for col, counter in criteria) + (rand[f"{r['auditor']}|{r['key']}"],)
            if best_score is None or score < best_score:
                best, best_score = idx, score
        if best is None:
            break
        r = pool.loc[best]
        out.append(best)
        taken.add(r["key"])
        seen: set[int] = set()
        for col, counter in criteria:
            if id(counter) not in seen:  # a counter shared by two criteria counts once
                counter[r[col]] += 1
                seen.add(id(counter))
        if not any(counter is run_count for _, counter in criteria):
            run_count[r["run_id"]] += 1
    return out


def draw_sample(cands: pd.DataFrame, seed: int = SEED, n_misses: int = N_MISSES, n_hits: int = N_HITS) -> pd.DataFrame:
    """The reaction test's cases: misses stratified by the kind of the first wrong fact (equal shares,
    what a kind can't give shared among the others), then hits as controls. Each command is used once,
    with one auditor's answer; no run gives more than RUN_CAP cases. Within a kind, picks balance the
    auditors (within the kind, then overall), then runs, harnesses and agent models."""
    rng = rng_for(seed, "reaction-sample")
    keys = sorted(f"{a}|{k}" for a, k in zip(cands["auditor"], cands["key"], strict=True))
    rand = dict(zip(keys, rng.random(len(keys)), strict=True))
    cands = cands.sort_values(["auditor", "key"]).reset_index(drop=True)
    misses = cands[cands["hit"] == 0.0]
    hits = cands[cands["hit"] == 1.0]
    avail = misses.groupby("miss_kind")["key"].nunique().to_dict()
    shares = allocate(n_misses, avail)
    taken: set[str] = set()
    run_count: Counter = Counter()
    model_count: Counter = Counter()
    auditor_count: Counter = Counter()
    chosen: list[dict[str, Any]] = []
    # scarcest kinds pick first, so they get first call on commands and runs
    for kind in sorted(shares, key=lambda k: (avail[k], k)):
        pool = misses[misses["miss_kind"] == kind]
        criteria = [("auditor", Counter()), ("auditor", auditor_count), ("run_id", run_count),
                    ("harness", Counter()), ("agent_model", model_count)]
        for idx in _pick(pool, shares[kind], taken, run_count, criteria, rand):
            chosen.append({**pool.loc[idx].to_dict(), "group": "miss"})
    short = n_misses - len(chosen)
    if short > 0:  # a command can be a miss of different kinds for different auditors: fill any gap
        criteria = [("miss_kind", Counter(c["miss_kind"] for c in chosen)), ("auditor", auditor_count),
                    ("run_id", run_count), ("harness", Counter()), ("agent_model", model_count)]
        for idx in _pick(misses, short, taken, run_count, criteria, rand):
            chosen.append({**misses.loc[idx].to_dict(), "group": "miss"})
    criteria = [("auditor", Counter()), ("run_id", run_count), ("harness", Counter()), ("agent_model", model_count)]
    for idx in _pick(hits, n_hits, taken, run_count, criteria, rand):
        chosen.append({**hits.loc[idx].to_dict(), "group": "hit"})
    out = pd.DataFrame(chosen).reset_index(drop=True)
    out["kind_order"] = out["miss_kind"].map({k: i for i, k in enumerate(KINDS)}).fillna(len(KINDS))
    out = out.sort_values(["group", "kind_order", "key"], ascending=[False, True, True]).drop(columns="kind_order")
    out.insert(0, "case_id", [f"rx-{i:03d}" for i in range(len(out))])
    out["seed"] = seed
    return out.reset_index(drop=True)


def sample_summary(sample: pd.DataFrame, dropped: pd.DataFrame | None = None) -> str:
    lines = [(f"{len(sample)} cases: {int((sample['group'] == 'miss').sum())} misses, "
              f"{int((sample['group'] == 'hit').sum())} hits; {sample['run_id'].nunique()} runs")]
    m = sample[sample["group"] == "miss"]
    lines.append("misses by kind of first wrong fact: " + ", ".join(
        f"{KIND_NAMES[k]} {int((m['miss_kind'] == k).sum())}" for k in KINDS))
    for col in ("auditor", "harness", "agent_model", "family", "situation"):
        tab = pd.crosstab(sample[col], sample["group"])
        lines.append(f"\nby {col}:\n{tab.to_string()}")
    lines.append("\ncases per run: " + ", ".join(f"{k} {v}" for k, v in sample["run_id"].value_counts().items()))
    if dropped is not None and len(dropped):
        lines.append("\nanswers left out (all auditors):\n" + dropped["reason"].value_counts().to_string())
    return "\n".join(lines)


# --- building the inputs -------------------------------------------------------------------------------------

INSPECT_CHECK_MB = 60.0
"""Logs whose sample is at most this many megabytes (uncompressed) are also read with Inspect's own reader,
to check the rebuilt R input against it byte for byte (bigger ones would not fit in memory)."""


def logged_input_tokens(output: dict[str, Any] | None) -> int | None:
    """The input tokens the logged call was charged for (uncached, cache reads and cache writes together:
    Inspect reports them apart for every provider)."""
    usage = (output or {}).get("usage") or {}
    parts = [usage.get(k) for k in ("input_tokens", "input_tokens_cache_read", "input_tokens_cache_write")]
    if all(p is None for p in parts):
        return None
    return int(sum(p or 0 for p in parts))


def _input_chars(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> int:
    from swarmbench.studies.auditor.reaction_inputs import message_text

    return sum(len(message_text(m)) for m in messages) + len(json.dumps(tools or []))


def inputs_path(out_dir: Path, case_id: str) -> Path:
    return out_dir / "inputs" / f"{case_id}.json.gz"


def save_inputs(out_dir: Path, case: dict[str, Any], built: Any) -> Path:
    """The exact request parts for one case (model, tools, tool choice, config, the A and R messages) and
    the logged next call's output, plus a small text file showing the one message that differs."""
    import gzip

    from swarmbench.studies.auditor.reaction_inputs import message_text

    path = inputs_path(out_dir, case["case_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"case_id": case["case_id"], "key": case["key"], "auditor": case["auditor"], "model": built.model,
              "tools": built.tools, "tool_choice": built.tool_choice, "config": built.config,
              "target_index": built.target_index, "A": built.a_input, "R": built.r_input,
              "logged_output": built.logged_output}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
    i = built.target_index
    diff = (f"{case['case_id']}  {case['key']}\nauditor {case['auditor']}; agent model {built.model}; "
            f"message {i} of {len(built.r_input)} (the only one that differs)\n\n"
            f"===== R (real, as logged) =====\n{message_text(built.r_input[i])}\n\n"
            f"===== A (auditor's prediction in the same wrapper) =====\n{message_text(built.a_input[i])}\n")
    (path.parent / f"{case['case_id']}_target.txt").write_text(diff)
    return path


def load_inputs(out_dir: Path, case_id: str) -> dict[str, Any]:
    import gzip

    with gzip.open(inputs_path(out_dir, case_id), "rt", encoding="utf-8") as f:
        return json.load(f)


def build_inputs(sample: pd.DataFrame, out_dir: Path = OUT_DIR, runs_dir: Path = RUNS_DIR,
                 inspect_check_mb: float = INSPECT_CHECK_MB, echo: Any = print) -> pd.DataFrame:
    """Rebuild every case's A and R inputs, one run log at a time, and check them (see
    ``reaction_inputs``). Writes ``build.parquet`` and adds the cases that can't be built to
    ``unbuildable.json`` (the next ``sample`` draws replacements for them)."""
    import asyncio
    import gc

    from swarmbench.studies.auditor.reaction_inputs import (
        build_case,
        inspect_serialized,
        inspect_view,
        read_log_slice,
        sample_json_size,
    )
    from swarmbench.studies.auditor.reaction_run import custom_call_check

    rows = []
    for run in sorted(sample["run_id"].unique()):
        sub = sample[sample["run_id"] == run]
        log_path = runs_dir / run / "logs" / sub["log_file"].iloc[0]
        sl = read_log_slice(log_path, set(sub["result_event"]))
        size_mb = sample_json_size(log_path) / 1e6
        view = inspect_view(log_path, set(sub["result_event"])) if size_mb <= inspect_check_mb else {}
        for case in sub.to_dict("records"):
            b = build_case(case, sl)
            row: dict[str, Any] = {
                "case_id": case["case_id"], "auditor": case["auditor"], "key": case["key"], "run_id": run,
                "harness": case["harness"], "agent_model": case["agent_model"], "ok": b.ok, "reason": b.reason,
                "model": b.model, "log_mb": round(size_mb, 1),
                **{k: (json.dumps(v) if isinstance(v, list) else v) for k, v in b.checks.items()},
            }
            if b.ok:
                problems = []
                row["inspect_identical"] = None  # not checked: the log is too big to load whole
                if case["result_event"] in view:
                    mine = inspect_serialized(b)
                    theirs = view[case["result_event"]]
                    row["inspect_identical"] = all(mine[k] == theirs[k] for k in mine)
                    if not row["inspect_identical"]:
                        problems.append("the rebuilt request differs from Inspect's own reading of the log")
                row["model_matches_sample"] = b.model == case["agent_model"]
                if not row["model_matches_sample"]:
                    problems.append(f"the next call went to {b.model}, not the run's agent model")
                row["custom_calls_ok"] = None  # only OpenAI's Responses API needs custom calls marked
                if str(b.model).startswith("openai/"):
                    check = asyncio.run(custom_call_check({"model": b.model, "R": b.r_input, "tools": b.tools,
                                                           "tool_choice": b.tool_choice, "config": b.config}))
                    row["custom_calls"] = check["custom_calls"]
                    row["custom_calls_ok"] = check["ok"]
                    if not check["ok"]:
                        problems.append("earlier custom tool calls would not be sent as custom calls")
                if problems:
                    row["ok"], row["reason"] = False, "; ".join(problems)
                    rows.append(row)
                    echo(f"  {case['case_id']} {case['harness']:12s} NOT BUILT: {row['reason']}")
                    continue
                row["logged_input_tokens"] = logged_input_tokens(b.logged_output)
                usage = (b.logged_output or {}).get("usage") or {}
                row["logged_output_tokens"] = usage.get("output_tokens")
                row["r_chars"] = _input_chars(b.r_input, b.tools)
                row["a_chars"] = _input_chars(b.a_input, b.tools)
                before = _input_chars(b.r_input[: b.target_index], b.tools)
                row["prefix_share"] = before / row["r_chars"] if row["r_chars"] else None
                row["max_tokens"] = (b.config or {}).get("max_tokens")
                # for the cap's worst case: no token is shorter than a byte
                row["r_bytes"] = len(json.dumps([b.r_input, b.tools], ensure_ascii=False).encode())
                row["a_target_bytes"] = len(json.dumps(b.a_input[b.target_index], ensure_ascii=False).encode())
                save_inputs(out_dir, case, b)
            rows.append(row)
            echo(f"  {case['case_id']} {case['harness']:12s} {'built' if b.ok else 'NOT BUILT: ' + str(b.reason)}")
        del sl, view
        gc.collect()
    df = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "build.parquet", index=False)
    failed = df[~df["ok"]]
    if len(failed):
        path = out_dir / "unbuildable.json"
        known = json.loads(path.read_text()) if path.exists() else []
        seen = {(r["auditor"], r["key"]) for r in known}
        known += [{"auditor": r["auditor"], "key": r["key"], "reason": r["reason"]}
                  for r in failed.to_dict("records") if (r["auditor"], r["key"]) not in seen]
        path.write_text(json.dumps(known, indent=1))
    return df


def build_summary(build: pd.DataFrame) -> str:
    ok = build[build["ok"]]
    lines = [f"{len(ok)} of {len(build)} cases built."]
    for r in build[~build["ok"]].to_dict("records"):
        lines.append(f"  not built: {r['case_id']} ({r['harness']}, {r['auditor']}): {r['reason']}")
    checks = [
        ("first_carrier", "the next call is the first model call whose input carries the result"),
        ("owner_is_agent", "that call sits in the same agent's span"),
        ("r_identical", "swapping the real payload back in gives the logged message byte for byte"),
        ("copy_identical", "a prediction that copies the real output exactly gives the logged message"),
        ("inspect_identical", "rebuilt R input, tools and settings equal Inspect's own reading of the log"),
        ("model_matches_sample", "the logged call's model is the run's agent model"),
        ("custom_calls_ok", "OpenAI requests send earlier custom tool calls (Codex's exec) as custom calls"),
    ]
    for col, what in checks:
        if col in ok:
            vals = ok[col].dropna().astype(bool)
            lines.append(f"  {what}: {int(vals.sum())} of {len(vals)} checked"
                         + (f" ({len(ok) - len(vals)} not checked: log too big to load whole)"
                            if col == "inspect_identical" else ""))
    if "a_differs_at" in ok:
        one = ok["a_differs_at"].map(lambda v: len(json.loads(v)) if isinstance(v, str) else 0)
        lines.append(f"  A differs from R in exactly one message: {int((one == 1).sum())}; "
                     f"in none (the prediction equals the real payload): {int((one == 0).sum())}")
    if "turn_results" in ok:
        lines.append(f"  cases whose turn had several results (only the target swapped): "
                     f"{int((ok['turn_results'] > 1).sum())}")
    return "\n".join(lines)


# --- comparing the actions -------------------------------------------------------------------------------------


def score(sample: pd.DataFrame, build: pd.DataFrame, answers: pd.DataFrame, out_dir: Path = OUT_DIR) -> pd.DataFrame:
    """One row per built case: the three next actions read by the rules in ``reaction_actions`` and the
    comparisons. A case counts in a comparison only when both its answers were given (not refused, not
    failed, not stopped by the cap)."""
    from swarmbench.studies.auditor.reaction_actions import read_action, same

    latest = {}
    for r in answers.to_dict("records"):
        latest[(r["case_id"], r["condition"])] = r
    rows = []
    built = set(build.loc[build["ok"], "case_id"])
    for case in sample.to_dict("records"):
        if case["case_id"] not in built:
            continue
        rec = load_inputs(out_dir, case["case_id"])
        if rec.get("key") != case["key"]:
            raise SystemExit(f"{case['case_id']}: its inputs were built for another command; run build again")
        logged = read_action(rec.get("logged_output"), case["function"], case["arguments"])
        row = {k: case.get(k) for k in ("case_id", "group", "miss_kind", "wrong_kinds", "auditor", "harness",
                                       "agent_model", "run_id", "agent", "family", "situation", "key")}
        row.update(l_category=logged.category, l_target=logged.target, l_text=logged.text)
        actions = {"L": logged}
        for cond in ("A", "R"):
            ans = latest.get((case["case_id"], cond)) or {}
            row[f"{cond.lower()}_status"] = ans.get("status", "missing")
            row[f"{cond.lower()}_stop_reason"] = ans.get("stop_reason")
            if ans.get("status") == "answered":
                act = read_action(ans.get("output"), case["function"], case["arguments"])
                actions[cond] = act
                row.update({f"{cond.lower()}_category": act.category, f"{cond.lower()}_target": act.target,
                            f"{cond.lower()}_text": act.text, f"{cond.lower()}_calls": act.calls})
        both = "A" in actions and "R" in actions
        row["scored"] = both
        for strict, tag in ((True, ""), (False, "_loose")):
            for x, y in (("A", "L"), ("R", "L"), ("A", "R")):
                val = float(not same(actions[x], actions[y], strict)) if both else np.nan
                row[f"{x.lower()}_ne_{y.lower()}{tag}"] = val
        rows.append(row)
        del rec
    return pd.DataFrame(rows)


# --- the results ----------------------------------------------------------------------------------------------

N_BOOT = 10_000


def _estimate(df: pd.DataFrame, values: np.ndarray, rng: np.random.Generator, n_boot: int) -> dict[str, Any]:
    """Mean with a cluster-bootstrap range: runs redrawn within scenario families, then agents within the
    drawn runs (the auditor study's two-stage scheme, ``analysis.estimate``)."""
    from swarmbench.studies.auditor.analysis import estimate

    if len(df) == 0:
        return {"estimate": None, "low": None, "high": None, "n": 0}
    clusters = (df["run_id"].astype(str) + "/" + df["agent"].astype(str)).tolist()
    est = estimate(values, clusters, df["family"].astype(str).tolist(), df["run_id"].astype(str).tolist(),
                   rng=rng, n_boot=n_boot)
    d = est.as_dict()
    return {"estimate": d["estimate"], "low": d["low"], "high": d["high"], "n": d["n"],
            "n_clusters": d["n_clusters"]}


def results(scores: pd.DataFrame, seed: int = SEED, n_boot: int = N_BOOT) -> dict[str, Any]:
    """The measures: how often A and R differ from L (and A from R), overall, for misses and hits, and by
    kind of wrong fact; the excess change rate P(A≠L) − P(R≠L), paired per case, with ranges."""
    rng = rng_for(seed, "reaction-results")
    s = scores[scores["scored"]]
    groups: list[tuple[str, pd.DataFrame]] = [("all cases", s), ("misses", s[s["group"] == "miss"]),
                                              ("hits", s[s["group"] == "hit"])]
    groups += [(f"misses: {KIND_NAMES[k]}", s[(s["group"] == "miss") & (s["miss_kind"] == k)]) for k in KINDS]
    out: dict[str, Any] = {"groups": [], "main": None}
    for name, df in groups:
        entry: dict[str, Any] = {"group": name, "n": len(df)}
        for tag, label in (("", "strict"), ("_loose", "loose")):
            a = df[f"a_ne_l{tag}"].to_numpy(dtype=float)
            r = df[f"r_ne_l{tag}"].to_numpy(dtype=float)
            ar = df[f"a_ne_r{tag}"].to_numpy(dtype=float)
            entry[label] = {
                "p_a_ne_l": _estimate(df, a, rng, n_boot),
                "p_r_ne_l": _estimate(df, r, rng, n_boot),
                "excess": _estimate(df, a - r, rng, n_boot),
                "p_a_ne_r": _estimate(df, ar, rng, n_boot),
            }
        out["groups"].append(entry)
    out["main"] = {"what": "excess change rate on misses: P(A≠L) − P(R≠L), strict",
                   **out["groups"][1]["strict"]["excess"]}
    m, h = s[s["group"] == "miss"], s[s["group"] == "hit"]
    out["misses_minus_hits"] = {
        "what": "excess change on misses minus excess change on hits (strict); unpaired, cases redrawn by group",
        "estimate": (float((m["a_ne_l"] - m["r_ne_l"]).mean() - (h["a_ne_l"] - h["r_ne_l"]).mean())
                     if len(m) and len(h) else None)}
    st = scores.melt(id_vars=["case_id"], value_vars=["a_status", "r_status"], var_name="condition",
                     value_name="status")
    out["statuses"] = st.groupby(["condition", "status"]).size().reset_index(name="n").to_dict("records")
    stops = pd.concat([scores["a_stop_reason"], scores["r_stop_reason"]]).fillna("none")
    out["stop_reasons"] = stops.value_counts().to_dict()
    out["refused"] = int(((scores["a_status"] == "refused") | (scores["r_status"] == "refused")).sum())
    out["n_scored"] = len(s)
    out["n_cases"] = len(scores)
    return out


def _fmt(e: dict[str, Any]) -> str:
    if e.get("estimate") is None:
        return "  n/a"
    return f"{e['estimate']:+.2f} [{e['low']:+.2f}, {e['high']:+.2f}]" if e is not None else ""


def _fmt_p(e: dict[str, Any]) -> str:
    if e.get("estimate") is None:
        return "  n/a"
    return f"{e['estimate']:.2f} [{e['low']:.2f}, {e['high']:.2f}]"


def report_text(res: dict[str, Any], scores: pd.DataFrame, batch: str) -> str:
    lines = [f"Agent-reaction test, answers batch {batch}",
             (f"{res['n_scored']} of {res['n_cases']} built cases scored (both answers given); "
              f"{res['refused']} with a refused answer."),
             "",
             ("A = the agent's model after seeing the auditor's output; R = after seeing the real output again; "
              "L = what the agent really did next."),
             "Rates are shares of cases whose next actions differ; ranges are 95% cluster-bootstrap ranges.",
             ""]
    main = res["main"]
    lines.append(f"Main result: {main['what']} = {_fmt(main)} (n = {main['n']})")
    lines.append("")
    for label in ("strict", "loose"):
        lines.append(f"{label} (same category{' and same target' if label == 'strict' else ' only'}):")
        lines.append(f"  {'group':44s} {'n':>4s}  {'P(A≠L)':>18s}  {'P(R≠L)':>18s}  {'excess A−R':>20s}  {'P(A≠R)':>18s}")
        for g in res["groups"]:
            e = g[label]
            lines.append(f"  {g['group']:44s} {g['n']:4d}  {_fmt_p(e['p_a_ne_l']):>18s}  {_fmt_p(e['p_r_ne_l']):>18s}  "
                         f"{_fmt(e['excess']):>20s}  {_fmt_p(e['p_a_ne_r']):>18s}")
        lines.append("")
    lines.append("Answer statuses: " + ", ".join(f"{r['condition'][0].upper()} {r['status']} {r['n']}"
                                                for r in res["statuses"]))
    lines.append("Stop reasons: " + ", ".join(f"{k} {v}" for k, v in res["stop_reasons"].items()))
    if len(scores):
        lines.append("")
        lines.append("Next-action categories (L / A / R):")
        cats = pd.DataFrame({c: scores[f"{c.lower()}_category"].value_counts() if f"{c.lower()}_category" in scores
                             else pd.Series(dtype=int) for c in ("L", "A", "R")}).fillna(0).astype(int)
        lines.append(cats.to_string())
    return "\n".join(lines)


# --- command line ---------------------------------------------------------------------------------------------


def _paid(out_dir: Path) -> float:
    from swarmbench.studies.auditor.reaction_run import prior_spending

    return prior_spending(out_dir)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import asyncio

    ap = argparse.ArgumentParser(description="The agent-reaction test (see the module docstring).")
    sub = ap.add_subparsers(dest="what", required=True)
    p_sample = sub.add_parser("sample", help="draw the cases")
    p_sample.add_argument("--seed", type=int, default=SEED)
    p_sample.add_argument("--force", action="store_true", help="redraw even though paid answers exist")
    sub.add_parser("build", help="rebuild every case's A and R inputs from the run logs, and check them")
    p_run = sub.add_parser("run", help="ask the agents' models (dry run with --dry-run; real with --live)")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--live", action="store_true", help="allow calls to the real (paid) models")
    p_run.add_argument("--cap", type=float, required=True, help="hard dollar cap for the whole reaction test")
    p_run.add_argument("--batch", default=None)
    p_run.add_argument("--workers", type=int, default=None)
    p_run.add_argument("--limit", type=int, default=None, help="only the first N cases (testing)")
    p_run.add_argument("--cases", default=None, help="comma list of case ids")
    for name in ("score", "report"):
        p = sub.add_parser(name)
        p.add_argument("--batch", default="live")
        p.add_argument("--n-boot", type=int, default=N_BOOT)
    sub.add_parser("project", help="the projected cost of the live run, from the built cases")
    for p in sub.choices.values():
        p.add_argument("--out-dir", type=Path, default=OUT_DIR)
        p.add_argument("--data-dir", type=Path, default=DATA_DIR)
        p.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    a = ap.parse_args(argv)
    out: Path = a.out_dir
    out.mkdir(parents=True, exist_ok=True)

    if a.what == "sample":
        if _paid(out) > 0 and not a.force:
            print("paid answers exist for the current sample; redrawing would change the cases. Pass --force if "
                  "that is really meant.")
            return 2
        unb_path = out / "unbuildable.json"
        unbuildable = json.loads(unb_path.read_text()) if unb_path.exists() else []
        cands, dropped = candidates(a.data_dir, unbuildable=unbuildable)
        sample = draw_sample(cands, a.seed)
        sample.to_parquet(out / "sample.parquet", index=False)
        dropped.to_csv(out / "left_out.csv", index=False)
        text = sample_summary(sample, dropped)
        (out / "sample_summary.txt").write_text(text + "\n")
        print(text)
        print(f"\nwrote {out / 'sample.parquet'}; next: build")
        return 0

    sample = pd.read_parquet(out / "sample.parquet")
    if a.what == "build":
        df = build_inputs(sample, out, a.runs_dir)
        text = build_summary(df)
        (out / "build_summary.txt").write_text(text + "\n")
        print(text)
        if (~df["ok"]).any():
            print("\nsome cases could not be built; run sample again (it draws replacements), then build.")
        return 0

    build = pd.read_parquet(out / "build.parquet")
    if a.what == "project":
        from swarmbench.studies.auditor.reaction_run import projection, projection_text

        proj = projection(build)
        text = projection_text(proj)
        (out / "cost_projection.txt").write_text(text + "\n")
        proj.to_csv(out / "cost_projection.csv")
        print(text)
        return 0

    if a.what == "run":
        from swarmbench.studies.auditor.reaction_run import WORKERS, ReactionRun, RunSettings, prior_spending

        if a.dry_run == a.live:
            print("say --dry-run (free, mock model) or --live (real, paid; only after the user approved the cap)")
            return 2
        if a.live:
            from swarmbench.studies.auditor.runner import load_keys

            load_keys()
        prior = prior_spending(out) if a.live else 0.0  # for the message only: the run reads it again under its lock
        batch = a.batch or ("live" if a.live else "dryrun")
        settings = RunSettings(batch=batch, out_dir=out, cap_usd=a.cap, dry_run=a.dry_run, live=a.live,
                               workers=a.workers or WORKERS, limit=a.limit,
                               cases=a.cases.split(",") if a.cases else None)
        print(f"batch {batch}: {int(build['ok'].sum())} built cases, two requests each; cap ${a.cap:.2f} for the "
              f"whole test" + (f" (${prior:.2f} already in the ledger)" if prior else "")
              + (", mock model" if a.dry_run else ""))
        summary = asyncio.run(ReactionRun(settings, build).run())
        print(json.dumps(summary, indent=2))
        return 2 if summary.get("error") else 0

    from swarmbench.studies.auditor.reaction_run import load_answers

    answers = load_answers(out, a.batch)
    scores = score(sample, build, answers, out)
    scores.to_parquet(out / f"scores_{a.batch}.parquet", index=False)
    if a.what == "score":
        print(f"scored {int(scores['scored'].sum())} of {len(scores)} cases -> {out / f'scores_{a.batch}.parquet'}")
        return 0
    res = results(scores, n_boot=a.n_boot)
    (out / f"results_{a.batch}.json").write_text(json.dumps(res, indent=2, default=str))
    text = report_text(res, scores, a.batch)
    (out / f"report_{a.batch}.txt").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
