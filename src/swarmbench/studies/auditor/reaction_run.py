"""Sending the reaction test's requests to the agents' own models, and what that costs.

For every built case (``reaction.py build``) two requests go to the agent's own model, with the logged
call's tools, tool choice and generation settings: **A** (the auditor's predicted output in place of the
real one) and then **R** (the logged request unchanged). A goes first and R right after, so a provider
that caches prompt prefixes by itself (OpenAI, Gemini) can serve R's shared prefix from the cache.

Three ways to run:

- ``--dry-run``: Inspect's mock model answers every request with the logged answer (so A, R and L all
  agree and the scoring runs end to end), reporting the token counts the real call would have: the
  logged call's measured input tokens (exact for R; A adds the difference in the swapped text at the
  case's own characters-per-token rate) and its logged output tokens. Its usage is priced at the agent
  model's real prices, which gives the projected cost. Nothing is spent.
- a real run: needs ``--live``, after the user has approved the dollar cap.

Spending (the same safeguards as the auditor runner, ``runner.py``, whose helpers are reused): before
every call its worst case is reserved with the judge's budget guard and a call that doesn't fit under
the cap is refused, so spending can't pass the cap. The worst case is the measured input tokens plus a
quarter, at the dearer of the input and cache-write prices, plus the call's full output allowance
(``max_tokens`` from the logged settings) at the output price. Every dollar charged is appended to
``spend_ledger.jsonl`` in the reaction folder (separate from the auditor study's ledger); the cap
counts everything in it. Only one real run can go at a time.

A refusal (the provider's content filter, or the model declining: ``runner.refusal_of``) is asked once
more; if refused again, the answer is recorded as ``refused`` with its stop reason. A call that fails
for a technical reason is retried by the budget guard (each attempt with its own reservation).

Files, in ``runs/_studies/auditor_general/reaction/answers/``: ``<batch>.jsonl`` (one line per request:
case, condition A or R, model, the request's hash, status, stop reason, refusal, the answer, usage,
dollars) and ``<batch>_summary.json``. The exact requests are the build's ``inputs/<case>.json.gz``;
the hash in each line is ``request_hash`` of what was sent, so they can be checked against each other.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from swarmbench.studies.auditor.runner import (
    SpendLedger,
    _json_default,
    billing_unknown,
    model_args,
    refusal_of,
)

LEDGER_FILE = "spend_ledger.jsonl"
CONDITIONS = ("A", "R")
WORKERS = 8
WORST_CASE_INPUT_MARGIN = 1.25
DEFAULT_MAX_OUTPUT = 32_000
"""The output allowance assumed for the worst case when the logged settings give none."""

_CALL: ContextVar[dict[str, Any] | None] = ContextVar("reaction_call", default=None)
"""What the call in flight is (case, condition, measured tokens), for the cap's worst case and the mock."""


# --- tokens and prices -----------------------------------------------------------------------------------


def provider_of(model: str) -> str:
    return model.split("/", 1)[0]


def price_note(model: str) -> str:
    """Where a model's price comes from, and whether it is uncertain for the way it is called here."""
    from swarmbench.costs import price_source

    src = price_source(model)
    unsure = []
    if "assumed" in src:
        unsure.append("no real price known; a deliberately high rate is used")
    elif "OpenRouter" in src and provider_of(model) in ("anthropic", "openai"):
        unsure.append("OpenRouter's list price, but the model is called directly through its own provider")
    if provider_of(model) == "openai" and "OpenRouter" in src:
        unsure.append("OpenAI charges no extra for cache writes; the list's cache-write price may overstate")
    return src + ("; UNSURE: " + "; ".join(unsure) if unsure else "")


def estimated_tokens(row: dict[str, Any], condition: str) -> int:
    """Input tokens of one request: the logged call's measured count for R (the request is the same), and
    for A that count plus the change in length of the swapped text at the case's own rate."""
    measured = row.get("logged_input_tokens")
    r_chars = float(row.get("r_chars") or 0)
    a_chars = float(row.get("a_chars") or r_chars)
    if measured is None or pd.isna(measured):
        measured = int(r_chars / 3.5)
    measured = int(measured)
    if condition == "R" or r_chars <= 0:
        return measured
    return max(1, round(measured * a_chars / r_chars))


def prefix_share(row: dict[str, Any]) -> float:
    """The share of the request before the swapped message (the part A and R have in common)."""
    share = row.get("prefix_share")
    return 0.9 if share is None or pd.isna(share) else float(share)


def call_costs(model: str, row: dict[str, Any], output_tokens: int | None = None) -> dict[str, float]:
    """Projected dollars for one case's two requests, three ways:

    - ``expected``: Anthropic writes the whole prompt to its cache on every call (Inspect marks cache
      points; A and R part where the swapped message is, so R can't count on reading A's), priced at the
      cache-write rate; OpenAI and OpenRouter cache prefixes by themselves with no write charge, so A pays
      the input rate and R reads the part before the swapped message at the cache-read rate.
    - ``no_cache``: both requests at the dearer of the input and cache-write rates.
    - ``worst``: the cap's reservation for both (see the module docstring).

    Output: the logged answer's output tokens (thinking included) for each request."""
    from swarmbench.costs import price_of

    p = price_of(model)
    write = p.input_cache_write if p.input_cache_write is not None else p.input
    read = p.input_cache_read if p.input_cache_read is not None else p.input
    dear = max(p.input, write or 0.0)
    logged_out = row.get("logged_output_tokens")
    logged_out = 1000 if logged_out is None or pd.isna(logged_out) else int(logged_out)
    out_tokens = int(output_tokens if output_tokens is not None else logged_out)
    a_in, r_in = estimated_tokens(row, "A"), estimated_tokens(row, "R")
    out_usd = 2 * out_tokens * p.output / 1e6
    if provider_of(model) == "anthropic":
        expected = (a_in + r_in) * write / 1e6 + out_usd
    else:
        shared = int(r_in * prefix_share(row))
        expected = (a_in * p.input + shared * read + (r_in - shared) * p.input) / 1e6 + out_usd
    no_cache = (a_in + r_in) * dear / 1e6 + out_usd
    max_out = row.get("max_tokens")
    max_out = DEFAULT_MAX_OUTPUT if max_out is None or pd.isna(max_out) else int(max_out)
    worst = ((a_in + r_in) * WORST_CASE_INPUT_MARGIN * dear + 2 * max_out * p.output) / 1e6
    return {"expected": expected, "no_cache": no_cache, "worst": worst, "input_tokens_a": a_in,
            "input_tokens_r": r_in, "output_tokens": out_tokens}


def projection(build: pd.DataFrame) -> pd.DataFrame:
    """Projected cost by agent model (and in total), from the built cases."""
    rows = []
    for r in build[build["ok"]].to_dict("records"):
        c = call_costs(r["model"], r)
        rows.append({"model": r["model"], **c})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    g = df.groupby("model").agg(cases=("expected", "size"), input_tokens_per_request=("input_tokens_r", "mean"),
                                output_tokens_per_request=("output_tokens", "mean"),
                                expected_usd=("expected", "sum"), no_cache_usd=("no_cache", "sum"),
                                worst_usd=("worst", "sum"))
    g["expected_per_case"] = g["expected_usd"] / g["cases"]
    g["no_cache_per_case"] = g["no_cache_usd"] / g["cases"]
    g["price"] = [price_note(m) for m in g.index]
    total = pd.DataFrame([{"cases": g["cases"].sum(),
                           "input_tokens_per_request": df["input_tokens_r"].mean(),
                           "output_tokens_per_request": df["output_tokens"].mean(),
                           "expected_usd": g["expected_usd"].sum(), "no_cache_usd": g["no_cache_usd"].sum(),
                           "worst_usd": g["worst_usd"].sum(),
                           "expected_per_case": g["expected_usd"].sum() / g["cases"].sum(),
                           "no_cache_per_case": g["no_cache_usd"].sum() / g["cases"].sum(), "price": ""}],
                         index=["TOTAL"])
    return pd.concat([g, total])


def projection_text(proj: pd.DataFrame) -> str:
    if proj.empty:
        return "(no built cases)"
    lines = [(f"{'agent model':42s} {'cases':>5s} {'in tok/req':>10s} {'out tok':>7s} {'$/case':>7s} "
              f"{'expected':>9s} {'no cache':>9s} {'worst':>8s}  price source")]
    for name, r in proj.iterrows():
        lines.append(f"{name!s:42s} {int(r['cases']):5d} {r['input_tokens_per_request']:10,.0f} "
                     f"{r['output_tokens_per_request']:7,.0f} {r['expected_per_case']:7.3f} "
                     f"{r['expected_usd']:9.2f} {r['no_cache_usd']:9.2f} {r['worst_usd']:8.2f}  {r['price']}")
    return "\n".join(lines)


# --- requests ----------------------------------------------------------------------------------------------


def request_parts(rec: dict[str, Any], condition: str) -> tuple[list[Any], list[Any], Any, Any]:
    """Inspect objects for one request: messages, tools, tool choice, generation settings."""
    from inspect_ai.event._validate import validate_chat_messages
    from inspect_ai.model import GenerateConfig
    from inspect_ai.tool import ToolFunction, ToolInfo

    messages = validate_chat_messages(rec[condition], context={"deserializing": True})
    tools = [ToolInfo.model_validate(t) for t in rec.get("tools") or []]
    tc = rec.get("tool_choice")
    if isinstance(tc, dict) and tc.get("name"):
        tc = ToolFunction(name=tc["name"])
    config = GenerateConfig.model_validate(rec.get("config") or {})
    return messages, tools, tc, config


def request_hash(rec: dict[str, Any], condition: str) -> str:
    """A hash of exactly what is sent for one request (messages, tools, tool choice, settings, model)."""
    payload = json.dumps([rec.get("model"), rec[condition], rec.get("tools"), rec.get("tool_choice"),
                          rec.get("config")], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _max_tokens(rec: dict[str, Any]) -> int:
    return int((rec.get("config") or {}).get("max_tokens") or DEFAULT_MAX_OUTPUT)


# --- the models ---------------------------------------------------------------------------------------------


def mock_model() -> Any:
    """Inspect's mock model answering every request with the logged answer, with the token counts the real
    request would have (priced later at the agent model's prices)."""
    from inspect_ai.model import ModelOutput, ModelUsage, get_model

    def outputs(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        call = _CALL.get() or {}
        logged = call.get("logged_output") or {}
        out = ModelOutput.model_validate(logged) if logged.get("choices") else ModelOutput.from_content(
            model="mockllm/model", content="")
        out.model = "mockllm/model"
        row = call.get("row") or {}
        tokens_in = estimated_tokens(row, call.get("condition", "R"))
        out_tokens = int(row.get("logged_output_tokens") or 0)
        model = call.get("model") or ""
        if provider_of(model) == "anthropic":
            usage = ModelUsage(input_tokens=0, input_tokens_cache_write=tokens_in, output_tokens=out_tokens)
        elif call.get("condition") == "R":
            shared = int(tokens_in * prefix_share(row))
            usage = ModelUsage(input_tokens=tokens_in - shared, input_tokens_cache_read=shared,
                               output_tokens=out_tokens)
        else:
            usage = ModelUsage(input_tokens=tokens_in, output_tokens=out_tokens)
        usage.total_tokens = tokens_in + out_tokens
        out.usage = usage
        return out

    return get_model("mockllm/model", custom_outputs=outputs)


def worst_case_fn() -> Any:
    """The cap's reservation for the call in flight: measured input tokens plus a quarter at the dearer
    input rate, and the full output allowance at the output rate (``JudgeBudget``'s estimate signature)."""
    from swarmbench.costs import price_of

    def estimate(model: Any, input: Any, config: Any = None) -> tuple[float | None, int]:
        call = _CALL.get() or {}
        name = call.get("model") or str(model)
        p = price_of(name)
        dear = max(p.input, p.input_cache_write or 0.0)
        tokens_in = int(estimated_tokens(call.get("row") or {}, call.get("condition", "R")) * WORST_CASE_INPUT_MARGIN)
        max_out = int(call.get("max_tokens") or DEFAULT_MAX_OUTPUT)
        return (tokens_in * dear + max_out * p.output) / 1e6, tokens_in + max_out

    return estimate


@dataclass
class RunSettings:
    batch: str
    out_dir: Path
    cap_usd: float
    dry_run: bool = True
    live: bool = False
    workers: int = WORKERS
    limit: int | None = None
    cases: list[str] | None = None
    quiet: bool = False

    @property
    def answers_dir(self) -> Path:
        return self.out_dir / "answers"


@dataclass
class ReactionRun:
    s: RunSettings
    build: pd.DataFrame
    model_factory: Any = None
    """Tests pass a function name -> model; real runs use Inspect's get_model."""
    spent: float = 0.0
    statuses: dict[str, int] = field(default_factory=dict)
    stop: bool = False

    def __post_init__(self) -> None:
        from swarmbench.judge.budget import JudgeBudget
        from swarmbench.types import CostSummary

        if not self.s.dry_run and not self.s.live:
            raise SystemExit("refusing to call the agents' models: a real run needs --live (and the user's approval "
                             "of the cap). Use --dry-run to test for free.")
        self.live = not self.s.dry_run
        self.ledger = SpendLedger(self.s.out_dir / LEDGER_FILE) if self.live else None
        self.budget = JudgeBudget(cap_usd=self.s.cap_usd, spent_fn=lambda: CostSummary(tokens=0, usd=self.spent),
                                  estimate_fn=worst_case_fn())
        self.models: dict[str, Any] = {}
        self._mock = mock_model() if self.s.dry_run else None
        if self._mock is not None:
            self.budget.guard(self._mock)

    def model(self, name: str) -> Any:
        if self._mock is not None:
            return self._mock
        if name not in self.models:
            if self.model_factory is not None:
                m = self.model_factory(name)
            else:
                from inspect_ai.model import get_model

                m = get_model(name, **model_args(name))
            self._charge_failures(m, name)
            self.budget.guard(m)
            self.models[name] = m
        return self.models[name]

    def _charge_failures(self, model: Any, name: str) -> None:
        """A failed attempt that may still have been billed (a time-out, a dropped connection) is charged at
        its worst case, as the auditor runner does."""
        original = model.generate
        estimate = worst_case_fn()

        async def generate(input: Any, *args: Any, **kwargs: Any) -> Any:
            call = _CALL.get()
            if call is not None:
                call["attempts"] = call.get("attempts", 0) + 1
            try:
                return await original(input, *args, **kwargs)
            except Exception as exc:
                if self.live and billing_unknown(exc):
                    usd, _ = estimate(model, input, kwargs.get("config"))
                    self.spent += usd or 0.0
                    if self.ledger is not None:
                        self.ledger.append({"batch": self.s.batch, "case_id": (call or {}).get("case_id"),
                                            "condition": (call or {}).get("condition"), "model": name, "usd": usd,
                                            "kind": f"failed attempt, maybe billed ({type(exc).__name__})"})
                raise

        model.generate = generate

    # -- running

    def jobs(self) -> list[dict[str, Any]]:
        ok = self.build[self.build["ok"]].sort_values("case_id")
        if self.s.cases:
            ok = ok[ok["case_id"].isin(self.s.cases)]
        if self.s.limit is not None:
            ok = ok.head(self.s.limit)
        return ok.to_dict("records")

    async def run(self) -> dict[str, Any]:
        with self._live_lock():
            return await self._run()

    @contextlib.contextmanager
    def _live_lock(self) -> Any:
        if not self.live:
            yield
            return
        import fcntl

        self.s.answers_dir.mkdir(parents=True, exist_ok=True)
        with (self.s.out_dir / ".live.lock").open("w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SystemExit("another real reaction run is going; wait for it to finish") from exc
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    async def _run(self) -> dict[str, Any]:
        from swarmbench.studies.auditor.reaction import load_inputs

        self.s.answers_dir.mkdir(parents=True, exist_ok=True)
        path = self.s.answers_dir / f"{self.s.batch}.jsonl"
        started = time.monotonic()
        jobs = self.jobs()
        sem = asyncio.Semaphore(max(1, self.s.workers))
        with path.open("w") as f:

            async def one(row: dict[str, Any]) -> None:
                async with sem:
                    rec = load_inputs(self.s.out_dir, row["case_id"])
                    for cond in CONDITIONS:
                        line = await self.ask(row, rec, cond)
                        f.write(json.dumps(line, default=_json_default, ensure_ascii=False) + "\n")
                        f.flush()
                    del rec

            await asyncio.gather(*(one(r) for r in jobs))
        summary = {"batch": self.s.batch, "dry_run": self.s.dry_run, "cases": len(jobs),
                   "requests": sum(self.statuses.values()), "statuses": self.statuses,
                   ("projected_usd" if self.s.dry_run else "spent_usd"): round(self.spent, 4),
                   "cap_usd": self.s.cap_usd, "cap_reached": self.stop or self.budget.hit,
                   "seconds": round(time.monotonic() - started, 1), "answers": str(path),
                   "time": datetime.now(UTC).isoformat()}
        (self.s.answers_dir / f"{self.s.batch}_summary.json").write_text(json.dumps(summary, indent=2))
        return summary

    async def ask(self, row: dict[str, Any], rec: dict[str, Any], condition: str) -> dict[str, Any]:
        from swarmbench.costs import usage_cost
        from swarmbench.judge.budget import JudgeBudgetExhausted

        name = rec["model"]
        base = {"case_id": row["case_id"], "condition": condition, "model": name, "batch": self.s.batch,
                "request_hash": request_hash(rec, condition), "dry_run": self.s.dry_run}
        if self.stop:
            return self._line(base, "not_run", error="not asked: the spending cap was reached")
        messages, tools, tool_choice, config = request_parts(rec, condition)
        call = {"case_id": row["case_id"], "condition": condition, "model": name, "row": row,
                "max_tokens": _max_tokens(rec), "logged_output": rec.get("logged_output"), "attempts": 0}
        token = _CALL.set(call)
        refusals, cost_total, last_error = 0, 0.0, None
        try:
            while True:
                try:
                    out = await self.model(name).generate(messages, tools=tools, tool_choice=tool_choice,
                                                          config=config)
                except JudgeBudgetExhausted as exc:
                    self.stop = True
                    return self._line(base, "not_run", error=f"not asked: the ${self.s.cap_usd:g} cap ({exc})",
                                      attempts=call["attempts"], usd=cost_total)
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                    return self._line(base, "error", error=last_error, attempts=call["attempts"], usd=cost_total)
                # priced at the agent model's prices (a dry run's mock usage too, which gives the projection)
                usd = float(usage_cost({name: out.usage}).usd or 0.0) if out.usage is not None else 0.0
                cost_total += usd
                self.spent += usd
                if self.ledger is not None:
                    self.ledger.append({"batch": self.s.batch, "case_id": row["case_id"], "condition": condition,
                                        "model": name, "usd": usd, "kind": "answer"})
                refusal = refusal_of(out)
                if refusal is not None and refusals == 0:
                    refusals += 1  # a refusal is asked once more (a classifier can clear on a second try)
                    continue
                status = "refused" if refusal is not None else "answered"
                return self._line(base, status, output=out.model_dump(mode="json", exclude_none=True),
                                  stop_reason=getattr(out, "stop_reason", None), refusal=refusal,
                                  usage=out.usage.model_dump(exclude_none=True) if out.usage else None,
                                  usd=cost_total, attempts=call["attempts"], refusals=refusals)
        finally:
            _CALL.reset(token)

    def _line(self, base: dict[str, Any], status: str, **extra: Any) -> dict[str, Any]:
        self.statuses[status] = self.statuses.get(status, 0) + 1
        done = sum(self.statuses.values())
        if not self.s.quiet and done % 20 == 0:
            print(f"  {done} requests, {'projected' if self.s.dry_run else 'spent'} ${self.spent:.2f} "
                  f"of ${self.s.cap_usd:g}, {self.statuses}", flush=True)
        return {**base, "status": status, "time": datetime.now(UTC).isoformat(), **extra}


def prior_spending(out_dir: Path) -> float:
    return SpendLedger(out_dir / LEDGER_FILE).total()


def load_answers(out_dir: Path, batch: str) -> pd.DataFrame:
    path = out_dir / "answers" / f"{batch}.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return pd.DataFrame(rows)
