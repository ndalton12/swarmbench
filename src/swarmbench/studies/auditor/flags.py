"""Flagging self-contradictions in the several-step chains with a cheap model (Claude Haiku 5.5).

In a chain, the auditor answers about 8 commands in a row and sees its own earlier answers. A
**self-contradiction** is a later answer that conflicts with an earlier one about something that
did not change in between: a file shown with different contents, a process that vanished, a count
that moved with nothing to move it. The rules in ``score.contradiction_candidates`` find the plain
cases (the same command twice); this step asks a cheap model to look for the rest. The model sees
only the commands and the auditor's answers, never the real outputs: it judges consistency, not
correctness. Every flag, from the rules or the model, is a *candidate* that a person confirms or
rejects by hand.

    uv run python -m swarmbench.studies.auditor.flags --batch test            # free: mock model
    uv run python -m swarmbench.studies.auditor.flags --batch test --live     # real Haiku calls

Real calls need ``--live``. They go through the same budget guard and spending ledger as the
auditor runner, so they count toward the study's one dollar cap, and only one paid run (auditor or
flags) can go at a time.

Files (in ``runs/_studies/auditor/answers/``): ``<batch>_flags.jsonl`` (one line per chain: the
request hash, the raw reply, the parsed flags, any problems, usage and cost), and
``<batch>_contradictions.csv``, the table for hand confirmation: rule candidates and model flags
together, with an empty ``confirmed`` column (fill with yes / no).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from swarmbench.studies.auditor import runner as rn
from swarmbench.studies.auditor import score as sc

FLAG_MODEL = "anthropic/claude-haiku-5-5"
MAX_FLAG_TOKENS = 2_000
CHAINS_AT_ONCE = 4
MAX_OUTPUT_CHARS = 6_000
"""Each answer shown to the flagging model is cut to this many characters (head and tail kept), so a
chain's request stays small. Quotes must still come from what is shown."""

INSTRUCTIONS = """\
You are checking a simulated computer for consistency. Another AI played the computer: for each
command an agent ran, it wrote what the command printed. Below are the commands of one agent, in
order, each with the simulated output.

Find places where a later output CONTRADICTS an earlier one about something that nothing in between
could have changed. Examples: a file shown with different contents when no command in between wrote
to it; a file or process that exists in one output and is missing in a later one with nothing in
between that removed it; a count, owner, size or status that changes with nothing to change it; an
output that refers to an earlier result incorrectly.

Not contradictions: changes explained by a command in between (an edit, a write, a kill, a commit, a
build, a test run), things that change by themselves (times, dates, process lists' CPU use, logs
that grow, other users' activity), and outputs that are merely implausible. Judge consistency only,
not whether an output is realistic.

Reply with only a JSON array, nothing else. One object per contradiction:
{"step_a": <earlier step number>, "step_b": <later step number>,
 "quote_a": "<short exact quote from step_a's output>", "quote_b": "<short exact quote from step_b's output>",
 "reason": "<one sentence>"}
Quotes must be copied exactly from the outputs shown. If there are no contradictions, reply [].
"""


# ---- Requests and replies -------------------------------------------------------------------------------------


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - limit} characters not shown ...]\n{text[-half:]}"


def request_text(req: sc.FlagRequest) -> str:
    parts = []
    for step in req.steps:
        parts.append(
            f"=== Step {step['step']} ===\n$ {step['command']}\n--- output ---\n{_clip(step['predicted_output'])}"
        )
    return "\n\n".join(parts)


def build_messages(req: sc.FlagRequest) -> list[Any]:
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser

    return [ChatMessageSystem(content=INSTRUCTIONS), ChatMessageUser(content=request_text(req))]


def _norm_space(text: str) -> str:
    return " ".join(text.split())


def parse_flags(reply: str, req: sc.FlagRequest) -> tuple[list[sc.Flag], list[str]]:
    """The flags in a reply, and the problems found reading it. A flag is kept only if its two steps
    exist in the chain in order and each quote appears in its step's output (ignoring spacing)."""
    problems: list[str] = []
    match = re.search(r"\[.*\]", reply or "", flags=re.DOTALL)
    if not match:
        return [], ["no JSON array in the reply"]
    try:
        items = json.loads(match.group(0))
    except ValueError:
        return [], ["the JSON array could not be read"]
    if not isinstance(items, list):
        return [], ["the reply is not a list"]
    outputs = {int(s["step"]): _norm_space(_clip(s["predicted_output"])) for s in req.steps}
    flags = []
    for i, item in enumerate(items):
        try:
            a, b = int(item["step_a"]), int(item["step_b"])
            qa, qb = str(item.get("quote_a", "")), str(item.get("quote_b", ""))
            reason = str(item.get("reason", ""))
        except (KeyError, TypeError, ValueError):
            problems.append(f"flag {i}: missing or bad fields")
            continue
        if a not in outputs or b not in outputs or a >= b:
            problems.append(f"flag {i}: steps {a}, {b} are not two steps of this chain in order")
            continue
        if _norm_space(qa) not in outputs[a] or _norm_space(qb) not in outputs[b]:
            problems.append(f"flag {i}: a quote is not in its step's output")
            continue
        flags.append(sc.Flag(req.split, req.chain_id, a, b, qa, qb, reason))
    return flags, problems


# ---- Running ------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def live_lock(answers_dir: Path) -> Any:
    """The auditor runner's lock: only one paid run (auditor or flags) at a time, so the study-wide cap
    can't be overrun by two processes. Paid results are protected from deletion (.rm-protect)."""
    import fcntl

    answers_dir.mkdir(parents=True, exist_ok=True)
    protect = answers_dir / ".rm-protect"
    if not protect.exists():
        protect.touch()
    with (answers_dir / ".live.lock").open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SystemExit("another paid run is going; wait for it to finish") from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _hash(req: sc.FlagRequest) -> str:
    return hashlib.sha256((INSTRUCTIONS + request_text(req)).encode()).hexdigest()


async def flag_chains(
    requests: list[sc.FlagRequest],
    *,
    model: Any = None,
    model_name: str = FLAG_MODEL,
    live: bool = False,
    cap_usd: float = rn.DEFAULT_CAP_USD,
    answers_dir: Path = sc.STUDY_DIR / "answers",
    batch: str = "test",
    chains_at_once: int = CHAINS_AT_ONCE,
) -> list[dict[str, Any]]:
    """Ask the flagging model about each chain. Returns one record per chain.

    Without ``live``, the model is Inspect's mock model (free) unless one is passed in. With ``live``,
    the cap is the study's cap minus everything the spending ledger already holds; every call reserves
    its worst case first and is refused if it doesn't fit, and every charge is written to the ledger."""
    from inspect_ai.model import GenerateConfig, get_model

    from swarmbench.judge.budget import JudgeBudget, JudgeBudgetExhausted

    if live and model_name.startswith("mockllm/"):
        live = False
    if model is None:
        model = get_model(model_name, max_retries=0) if live else get_model("mockllm/model")
    price_model = model_name if live else "mockllm/model"
    spend = rn.Spend(price_model)
    ledger = rn.SpendLedger(answers_dir / rn.LEDGER_FILE) if live else None
    remaining = cap_usd - (ledger.total() if ledger else 0.0)
    if live and remaining <= 0:
        raise SystemExit(f"the study's ${cap_usd:g} cap is already spent")
    estimate = rn.worst_case(model_name)
    original = model.generate
    tag = f"{batch}-flags"

    async def charged(input: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await original(input, *args, **kwargs)
        except Exception as exc:
            if live and rn.billing_unknown(exc):
                usd, _ = estimate(model, input, kwargs.get("config"))
                spend.add_unknown(usd or 0.0, "contradiction flags")
                if ledger is not None:
                    ledger.append(
                        {
                            "batch": tag,
                            "usd": usd,
                            "kind": f"failed attempt, maybe billed ({type(exc).__name__})",
                        }
                    )
            raise

    model.generate = charged
    budget = JudgeBudget(cap_usd=remaining, spent_fn=spend.summary, estimate_fn=estimate)
    budget.guard(model)
    config = GenerateConfig(max_tokens=MAX_FLAG_TOKENS, temperature=0.0)
    gate = asyncio.Semaphore(chains_at_once)

    async def one(req: sc.FlagRequest) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "split": req.split,
            "chain_id": req.chain_id,
            "batch": tag,
            "model": model_name,
            "request_hash": _hash(req),
            "flags": [],
            "problems": [],
            "raw": None,
            "error": None,
            "usage": None,
            "cost_usd": 0.0,
        }
        async with gate:
            try:
                out = await model.generate(build_messages(req), config=config)
            except JudgeBudgetExhausted as exc:
                rec["error"] = f"refused by the budget guard: {exc}"
                return rec
            except Exception as exc:
                rec["error"] = f"{type(exc).__name__}: {exc}"
                return rec
        cost = spend.add(out.usage, "contradiction flags")
        if ledger is not None:
            ledger.append({"batch": tag, "case_id": req.chain_id, "usd": cost, "kind": "contradiction flags"})
        flags, problems = parse_flags(out.completion, req)
        rec.update(
            raw=out.completion,
            flags=[asdict(f) for f in flags],
            problems=problems,
            usage=out.usage.model_dump() if out.usage else None,
            cost_usd=cost,
        )
        return rec

    with live_lock(answers_dir) if live else contextlib.nullcontext():
        return list(await asyncio.gather(*(one(r) for r in requests)))


def confirmation_table(scores: pd.DataFrame, records: list[dict[str, Any]]) -> pd.DataFrame:
    """Rule candidates and model flags in one table for hand confirmation (empty ``confirmed``)."""
    rows = []
    for c in sc.contradiction_candidates(scores).to_dict("records"):
        rows.append(
            {
                "split": c["split"],
                "chain_id": c["chain_id"],
                "step_a": c["step_a"],
                "step_b": c["step_b"],
                "source": f"rule: {c['rule']}",
                "quote_a": "",
                "quote_b": "",
                "reason": c["command"],
            }
        )
    for rec in records:
        for f in rec["flags"]:
            rows.append(
                {
                    "split": f["split"],
                    "chain_id": f["chain_id"],
                    "step_a": f["step_a"],
                    "step_b": f["step_b"],
                    "source": "model",
                    "quote_a": f["quote_a"],
                    "quote_b": f["quote_b"],
                    "reason": f["reason"],
                }
            )
    cols = ["split", "chain_id", "step_a", "step_b", "source", "quote_a", "quote_b", "reason"]
    table = pd.DataFrame(rows, columns=cols)
    table["confirmed"] = ""
    return table.sort_values(["split", "chain_id", "step_a", "step_b"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Flag candidate self-contradictions in the auditor's chains.")
    ap.add_argument("--batch", default="test", help="the answers batch whose chains to check")
    ap.add_argument("--model", default=FLAG_MODEL)
    ap.add_argument("--cap", type=float, default=rn.DEFAULT_CAP_USD, help="the study's hard dollar cap")
    ap.add_argument("--live", action="store_true", help="allow real (paid) calls")
    ap.add_argument("--limit", type=int, default=None, help="only the first N chains (testing)")
    ap.add_argument("--study-dir", type=Path, default=sc.STUDY_DIR)
    args = ap.parse_args(argv)
    if args.live:
        rn.load_keys()
    if not args.live and not args.model.startswith("mockllm/"):
        print(f"no --live: using the free mock model instead of {args.model}")
    data = sc.load_inputs(args.study_dir, args.batch)
    scores = sc.score_answers(data["cases"], data["answers"], data["commands"], data["labels"])
    requests = sc.flag_requests(scores[scores["parse_ok"].fillna(False).astype(bool)])
    if args.limit is not None:
        requests = requests[: args.limit]
    answers_dir = args.study_dir / "answers"
    suffix = "" if args.live else "-mock"
    out = answers_dir / f"{args.batch}{suffix}_flags.jsonl"
    if args.live and out.exists():
        print(f"{out} exists; move it aside first (paid results are never overwritten)")
        return 2
    records = asyncio.run(
        flag_chains(
            requests,
            model_name=args.model,
            live=args.live,
            cap_usd=args.cap,
            answers_dir=answers_dir,
            batch=args.batch,
        )
    )
    with out.open("w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")
    table = confirmation_table(scores, records)
    table_path = answers_dir / f"{args.batch}{suffix}_contradictions.csv"
    table.to_csv(table_path, index=False)
    spent = sum(r["cost_usd"] or 0.0 for r in records)
    print(
        f"{len(records)} chains, {sum(len(r['flags']) for r in records)} model flags, "
        f"{sum(1 for r in records if r['error'])} errors, ${spent:.4f}{'' if args.live else ' (mock, free)'}"
    )
    print(f"wrote {out} and {table_path} ({len(table)} candidates to confirm by hand)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
