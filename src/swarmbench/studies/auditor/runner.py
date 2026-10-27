"""Asking the auditor (stage 5).

Takes the drawn cases (``cases.py``), builds each request (``prompts.py``) and sends it to the auditor
through Inspect's ``get_model``. Every request and answer is saved, a hard dollar cap is enforced in
code, and the same pipeline can run with a stand-in model for free.

Three ways to run:

- ``--dry-run``: everything goes through Inspect's mock model, which writes plausible answers in the
  fixed format and reports token counts the way Anthropic would, prompt caching included. Its usage
  is priced as if it were the real auditor, so the run ends with a projected cost per item set
  against the plan's cost table. Nothing is spent.
- ``--replay BATCH``: re-runs from a batch's saved answers instead of calling any model (to redo the
  reading of answers, or to check that the requests come out the same).
- a real run: needs ``--live``. Not to be used until the user has approved the spending cap.

How requests are sent: every request starts with the fixed part (instructions plus the run's
description), marked as a prompt-cache breakpoint. Requests are grouped by run (and instruction
version); a group sends one request first, so the fixed part is stored, then the rest in parallel,
which read it back cheaply. Chains go step by step, each step's question marked so the next step
reads the conversation so far from the cache. Groups run a few at a time, so each group finishes well
within the cache's five-minute lifetime.

The cap: before every call, the worst case (the whole request at the full input price, no cache
discount, plus the maximum answer length at the output price) is reserved, using the judge's budget
guard (``swarmbench.judge.budget.JudgeBudget``). A call that doesn't fit is refused, so spending can't
pass the cap. Spending is priced with ``swarmbench.costs`` from the usage each answer reports.

Files (in ``runs/_studies/auditor/answers/``): ``<batch>.jsonl`` (one line per ask, the format agreed
with aud-analysis), ``<batch>_queue.jsonl`` (queue forecasts), ``<batch>_requests.jsonl`` (every
request in full, with its hash), ``<batch>_summary.json`` (spend and the cost projection).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from swarmbench.studies.auditor import prompts
from swarmbench.studies.auditor.cases import DATA_DIR, RUNS_DIR, commands_path, load_cases, load_commands

DEFAULT_MODEL = "anthropic/claude-opus-5-5"
DEFAULT_CAP_USD = 45.0
"""The user's approved hard cap for the whole study (doubled headline cases)."""
MAX_ANSWER_TOKENS = 8_000
MAX_ANSWER_TOKENS_REASONING = 16_000
"""For OpenAI and OpenRouter models the reasoning tokens count against the same limit and their amount at
medium effort is less known, so they get more room (the worst case reserved per call grows with it)."""
"""The longest answer allowed, also the worst case reserved per call. Opus 5.5's thinking counts towards it;
the longest real outputs drawn are about 18,000 characters (about 6,000 tokens)."""
DEFAULT_EFFORT = "medium"
"""Opus 5.5 always thinks; effort is the only control. Low keeps answers near the plan's length."""
WORKERS = 16
"""Calls in flight at once."""
MAX_RETRIES = 3
"""The pre-registered limit: a call that failed for a technical reason, or whose answer can't be read, is
asked again at most this many times; the last readable answer is kept."""
CACHE_TTL = "5m"
MIN_CACHEABLE_TOKENS = 512
"""Anthropic's smallest cacheable prefix for Opus 5.5; shorter prefixes are silently not cached."""

# Calls per item in the approved design (the plan's headline cases doubled), with the plan's cost table
# (docs/research/auditor-prediction-plan.md, "Cost") scaled to those calls at the plan's rate per call:
# item -> (calls, dollars at the plan's rate)
PLAN_COSTS: dict[str, tuple[int, float]] = {
    "one step (calls that matter and 30 that don't)": (270, round(5.20 / 150 * 270, 2)),
    "one step, long history": (20, 2.60),
    "several steps: chains": (512, round(6.10 / 256 * 512, 2)),
    "chain steps with the real past": (80, 2.80),
    "shared tool with the record": (200, round(5.10 / 100 * 200, 2)),
    "shared tool without the record": (40, 1.40),
    "waiting-line forecasts": (40, 1.10),
    "practice round (two instruction versions)": (100, 3.00),
    "self-consistency repeats": (20, 0.70),
    "storing scenario descriptions": (0, 1.50),
    "contradiction flags (Haiku, not built here)": (32, 0.10),
}


def item_of(ask: dict[str, Any]) -> str:
    """Which line of the plan's cost table an ask belongs to."""
    if ask.get("split") == "practice":
        return "practice round (two instruction versions)"
    if ask.get("situation") == "queue":
        return "waiting-line forecasts"
    sit, var = ask.get("situation"), ask.get("variant")
    return {
        ("one_step", "main"): "one step (calls that matter and 30 that don't)",
        ("one_step", "long_history"): "one step, long history",
        ("one_step", "repeat"): "self-consistency repeats",
        ("chain", "main"): "several steps: chains",
        ("chain", "real_past"): "chain steps with the real past",
        ("shared", "main"): "shared tool with the record",
        ("shared", "no_record"): "shared tool without the record",
    }.get((sit, var), f"{sit} {var}")


# --- settings ------------------------------------------------------------------------------------------


@dataclass
class Settings:
    batch: str
    split: str = "test"
    versions: list[str] = field(default_factory=lambda: [prompts.DEFAULT_VERSION])
    model: str = DEFAULT_MODEL
    cap_usd: float = DEFAULT_CAP_USD
    max_tokens: int | None = None
    """None: the provider's default (MAX_ANSWER_TOKENS for Anthropic, MAX_ANSWER_TOKENS_REASONING else)."""
    effort: str | None = DEFAULT_EFFORT
    dry_run: bool = False
    mock_style: str = "noisy"
    """Dry runs: "oracle" answers with the real output and time; "noisy" perturbs them (seeded)."""
    assume_thinking_tokens: int = 0
    """Dry runs: extra output tokens per call added to the projection, for the auditor's thinking."""
    replay: str | None = None
    live: bool = False
    limit: int | None = None
    situations: list[str] | None = None
    workers: int = WORKERS
    order: str = "random"
    """"random": a seeded random order across runs, families and situations (see AuditorRun.plan);
    "grouped": run by run, chains last (the old order, kept for comparison)."""
    resume: bool = False
    """Append to the batch's files and skip asks already done (the latest line per ask wins)."""
    retry_errors: bool = False
    """With resume: re-ask only the asks whose calls failed (and the chain steps after them)."""
    assumed_call_seconds: float = 20.0
    """Dry runs: how long one real call is assumed to take, for the simulated cache's clock."""
    data_dir: Path = DATA_DIR
    runs_dir: Path = RUNS_DIR
    quiet: bool = False

    @property
    def answers_dir(self) -> Path:
        return self.data_dir / "answers"


# --- spending -------------------------------------------------------------------------------------------


class Spend:
    """The running total, priced from each answer's reported usage."""

    def __init__(self, price_model: str) -> None:
        self.price_model = price_model
        self.usd = 0.0
        self.tokens = 0
        self.calls = 0
        self.by_item: dict[str, dict[str, float]] = {}

    def add(self, usage: Any, item: str) -> float:
        from swarmbench.costs import usage_cost

        if usage is None:
            return 0.0
        cost = usage_cost({self.price_model: usage}).usd or 0.0
        self.usd += cost
        self.tokens += usage.total_tokens or 0
        self.calls += 1
        row = self.by_item.setdefault(item, {"calls": 0, "usd": 0.0, "input": 0, "cache_read": 0,
                                             "cache_write": 0, "output": 0})
        row["calls"] += 1
        row["usd"] += cost
        row["input"] += usage.input_tokens or 0
        row["cache_read"] += usage.input_tokens_cache_read or 0
        row["cache_write"] += usage.input_tokens_cache_write or 0
        row["output"] += usage.output_tokens or 0
        return cost

    def add_unknown(self, usd: float, item: str) -> None:
        """A failed attempt that may have been billed: charged at its worst case."""
        self.usd += usd
        row = self.by_item.setdefault(item, {"calls": 0, "usd": 0.0, "input": 0, "cache_read": 0,
                                             "cache_write": 0, "output": 0})
        row["usd"] += usd

    def summary(self) -> Any:
        from swarmbench.types import CostSummary

        return CostSummary(tokens=self.tokens, usd=self.usd)


def provider_of(model: str) -> str:
    return model.split("/", 1)[0]


def default_max_tokens(model: str) -> int:
    return MAX_ANSWER_TOKENS if provider_of(model) == "anthropic" else MAX_ANSWER_TOKENS_REASONING


def generation_settings(model: str, effort: str | None, max_tokens: int | None) -> dict[str, Any]:
    """The GenerateConfig fields for one auditor model (also saved on every answer line).

    - Anthropic: ``effort`` (output_config.effort; Opus 5.5 always thinks, effort sets how much) and
      ``cache_prompt`` with our explicit cache breakpoints.
    - OpenAI: ``reasoning_effort`` (the Responses API's reasoning.effort). Caching is automatic; for
      gpt-5.6 and later Inspect also honours our explicit breakpoints (system and user text only).
    - OpenRouter (Gemini 4 Argon): ``reasoning_effort``, sent by Inspect as OpenRouter's
      ``reasoning: {effort}``, which OpenRouter maps to the model's thinking level. Inspect adds cache
      markers on OpenRouter only for anthropic/* models; Gemini caches implicitly (no write charge, hits
      not guaranteed).
    """
    provider = provider_of(model)
    out: dict[str, Any] = {"max_tokens": max_tokens or default_max_tokens(model), "timeout": 300}
    if provider == "anthropic":
        out.update(effort=effort, cache_prompt=True)
    elif provider in ("openai", "openrouter", "google", "grok", "together", "fireworks"):
        if effort:
            out["reasoning_effort"] = effort
    return {k: v for k, v in out.items() if v is not None}


def model_args(model: str) -> dict[str, Any]:
    """Arguments for get_model: the provider client's own retries off (the budget guard retries, each
    attempt with its own reservation); Anthropic's cache lifetime pinned to five minutes."""
    provider = provider_of(model)
    if provider == "anthropic":
        return {"cache_ttl": CACHE_TTL, "max_retries": 0}
    if provider in ("openai", "openrouter"):
        return {"max_retries": 0}
    return {}


CACHE_MODES = {"anthropic": ("explicit", 512), "openai": ("explicit", 1024), "openrouter": ("implicit", 1024)}
"""How each provider's prompt cache behaves, for the dry run's simulated usage: (mode, smallest cacheable
prefix in tokens). explicit: our breakpoints store the prefix (billed at the cache-write price) and later
calls read it; implicit: the provider reuses a recent prefix by itself, with no write charge."""


def refusal_of(out: Any) -> dict[str, Any] | None:
    """Whether an answer is a safety refusal, the same way for every provider: Anthropic and OpenRouter
    stop with stop_reason "content_filter"; OpenAI's Responses API also reports a model refusal as refusal
    text (``ContentText.refusal``) and a stop detail of type "refusal". Returns the kind, the category
    and any message the provider gave, or None."""
    choice = out.choices[0] if getattr(out, "choices", None) else None
    details = getattr(choice, "stop_details", None)
    refusal_text = []
    content = getattr(getattr(choice, "message", None), "content", None)
    if isinstance(content, list):
        refusal_text = [c.text for c in content if getattr(c, "refusal", False) and getattr(c, "text", None)]
    kind = None
    if getattr(out, "stop_reason", None) == "content_filter":
        kind = "content_filter"
    elif details is not None and getattr(details, "type", None) in ("refusal", "content_filter"):
        kind = details.type
    elif refusal_text:
        kind = "refusal"
    if kind is None:
        return None
    return {"kind": kind, "category": getattr(details, "category", None),
            "message": getattr(details, "explanation", None) or ("\n".join(refusal_text) or None)}


def worst_case(price_model: str) -> Any:
    """(model, input, config) -> (dollars, tokens): a bound the call can't cost more than. Input tokens
    are taken as the number of UTF-8 bytes (a token always covers at least one byte) plus an allowance
    for message framing, all priced at the dearer of the input and cache-write prices; the answer at its
    full allowed length at the output price."""
    from swarmbench.costs import price_of
    from swarmbench.judge.budget import JUDGE_MAX_OUTPUT_TOKENS

    price = price_of(price_model)
    per_input = max(price.input, price.input_cache_write or 0.0)

    def estimate(model: Any, input: Any, config: Any = None) -> tuple[float | None, int]:
        texts = [prompts_text(m) for m in input] if isinstance(input, list) else [str(input)]
        tokens_in = sum(len(t.encode()) for t in texts) + 50 * len(texts) + 200
        max_out = int(getattr(config, "max_tokens", None) or JUDGE_MAX_OUTPUT_TOKENS)
        usd = (tokens_in * per_input + max_out * price.output) / 1_000_000
        return usd, tokens_in + max_out

    return estimate


LEDGER_FILE = "spend_ledger.jsonl"


class SpendLedger:
    """Every dollar charged by real runs, one line per answer or maybe-billed failure, appended and never
    rewritten. The study-wide cap counts everything in it, whatever happens to the batch files."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, Any]) -> None:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {**record, "time": datetime.now(UTC).isoformat()}
        with self.path.open("a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(record, default=_json_default) + "\n")
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
        return out

    def total(self) -> float:
        return sum(float(r.get("usd") or 0.0) for r in self.records())

    def batches(self) -> set[str]:
        return {str(r.get("batch")) for r in self.records()}


_MAYBE_BILLED = {"APITimeoutError", "APIConnectionError", "ReadTimeout", "TimeoutError", "TimeoutException",
                 "RemoteProtocolError", "ReadError", "CancelledError"}


def billing_unknown(exc: BaseException) -> bool:
    """A failure after which the provider may still have done (and billed) the work."""
    names = {type(e).__name__ for e in (exc, exc.__cause__, exc.__context__) if e is not None}
    return bool(names & _MAYBE_BILLED) or isinstance(exc, TimeoutError)


def prompts_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return "".join(getattr(c, "text", "") or "" for c in content)


def request_hash(messages: list[Any]) -> str:
    from swarmbench.judge.calls import call_key

    return call_key(messages)


# --- the stand-in auditor for dry runs ----------------------------------------------------------------------


_TRUTH: ContextVar[dict[str, Any] | None] = ContextVar("auditor_truth", default=None)
"""What the mock auditor should answer for the call in flight (set by the job making the call)."""


class CacheSimulator:
    """Anthropic's prompt cache, roughly: each breakpoint stores the prefix up to it for five minutes;
    a request reads the longest stored prefix that matches its own breakpoints, pays the cache-write
    price for the rest up to its last breakpoint, and the full price after that."""

    def __init__(self, ttl_s: float = 300.0, clock: Any = None, mode: str = "explicit",
                 min_tokens: int = MIN_CACHEABLE_TOKENS) -> None:
        self.ttl_s = ttl_s
        self.clock = clock or time.monotonic
        self.mode = mode
        """explicit: breakpoints store prefixes, billed as cache writes; implicit: stored without a charge
        (the provider caches by itself); none: no caching at all."""
        self.min_tokens = min_tokens
        self.stored: dict[str, float] = {}

    def usage(self, messages: list[Any], output_tokens: int) -> Any:
        from inspect_ai.model import ModelUsage

        now = self.clock()
        blocks: list[tuple[str, bool]] = []
        for m in messages:
            content = m.content if isinstance(m.content, list) else [m.content]
            for c in content:
                text = c if isinstance(c, str) else getattr(c, "text", "")
                blocks.append((f"{m.role}\x1f{text}", bool(getattr(c, "cache_breakpoint", False))))
        sizes = [prompts.estimate_tokens(b) for b, _ in blocks]
        total = sum(sizes)
        h = hashlib.sha256()
        prefix_tokens = 0
        read = 0
        last_mark = 0
        for (text, mark), n in zip(blocks, sizes):
            h.update(text.encode())
            prefix_tokens += n
            if not mark:
                continue
            key = h.hexdigest()
            if prefix_tokens >= self.min_tokens and self.mode != "none":
                if self.stored.get(key, -math.inf) > now:
                    read = prefix_tokens
                self.stored[key] = now + self.ttl_s
                last_mark = prefix_tokens
        write = max(0, last_mark - read) if self.mode == "explicit" else 0
        plain = total - read - write
        return ModelUsage(input_tokens=plain, output_tokens=output_tokens, input_tokens_cache_read=read,
                          input_tokens_cache_write=write, total_tokens=total + output_tokens)


def mock_auditor(settings: Settings) -> Any:
    """Inspect's mock model, answering in the fixed format from the truth the job sets, with usage that
    follows Anthropic's caching rules."""
    from inspect_ai.model import ModelOutput, get_model

    calls = {"n": 0}
    limit = settings.max_tokens or default_max_tokens(settings.model)
    # simulated time: a real run sends about `workers` calls every `assumed_call_seconds`
    mode, min_tokens = CACHE_MODES.get(provider_of(settings.model), ("explicit", MIN_CACHEABLE_TOKENS))
    cache = CacheSimulator(clock=lambda: calls["n"] * settings.assumed_call_seconds / max(1, settings.workers),
                           mode=mode, min_tokens=min_tokens)
    rng = np.random.default_rng(7)

    def outputs(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        calls["n"] += 1
        truth = _TRUTH.get() or {}
        if truth.get("queue"):
            q = truth["queue"]
            text = (f"<typical_wait_seconds>{_num(q.get('real_typical_wait_s'), 30)}</typical_wait_seconds>\n"
                    f"<waiting_in_5_min>{int(_num(q.get('real_waiting_5min'), 0))}</waiting_in_5_min>\n"
                    f"<waiting_in_10_min>{int(_num(q.get('real_waiting_10min'), 0))}</waiting_in_10_min>\n"
                    f"<hits_limit>{'yes' if q.get('real_hits_limit') else 'no'}</hits_limit>")
        else:
            out = str(truth.get("output") or "")
            secs = max(0.1, float(_num(truth.get("seconds"), 1.0)))
            if settings.mock_style == "noisy":
                secs *= float(np.exp(rng.normal(0, 0.8)))
                if rng.random() < 0.2:
                    out = "bash: command failed"
            out = out[: int(limit * prompts.CHARS_PER_TOKEN * 0.9)]
            text = prompts.format_answer(out, round(secs, 1), round(secs / 2, 1), round(secs * 2, 1),
                                         exit_code=truth.get("exit_code"),
                                         will_wait=truth.get("will_wait"))
        out_tokens = min(limit, prompts.estimate_tokens(text) + settings.assume_thinking_tokens)
        result = ModelOutput.from_content(model="mockllm/model", content=text)
        result.usage = cache.usage(input, out_tokens)
        return result

    return get_model("mockllm/model", custom_outputs=outputs)


def _num(v: Any, default: float) -> float:
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def replay_auditor(saved: dict[tuple[str, str], dict[str, Any]], misses: list[str]) -> Any:
    """A mock model answering each ask with the raw answer saved for it, never calling a model. The job
    sets which ask is in flight; an ask that wasn't saved fails."""
    from inspect_ai.model import ModelOutput, get_model

    def outputs(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        truth = _TRUTH.get() or {}
        rec = saved.get((truth.get("case_id"), truth.get("version")))
        if rec is None or rec.get("error"):
            misses.append(f"{truth.get('case_id')}/{truth.get('version')}")
            raise RuntimeError(f"no saved answer for {truth.get('case_id')} (version {truth.get('version')})")
        if rec.get("request_hash") and rec["request_hash"] != request_hash(input):
            misses.append(f"{truth.get('case_id')}/{truth.get('version')} (request changed)")
        out = ModelOutput.from_content(model="replay", content=rec.get("raw") or "")
        from inspect_ai.model import ModelUsage

        out.usage = ModelUsage()
        return out

    return get_model("mockllm/model", custom_outputs=outputs)


# --- jobs ------------------------------------------------------------------------------------------------


@dataclass
class Job:
    """One unit of work: a single ask, a whole chain (its steps in order), or a queue moment."""

    kind: str  # "single" | "chain" | "queue"
    asks: list[dict[str, Any]]
    version: str
    family: str  # requests sharing one fixed part: "main" or "queue"
    start: int = 0
    """A resumed chain starts at this step ..."""
    past: list[str] = field(default_factory=list)
    """... with the saved answers to the steps before it as its history."""


class AuditorRun:
    def __init__(self, settings: Settings, cases: pd.DataFrame, queue: pd.DataFrame, commands: pd.DataFrame,
                 model: Any = None, queue_tools: Any = None) -> None:
        from swarmbench.judge.budget import JudgeBudget

        self.queue_tools = queue_tools
        """aud-yardsticks' queue_sim (or a stand-in in tests) for what is running and waiting at a moment."""

        self.s = settings
        self.cases = cases
        self.queue = queue
        self.commands = commands
        self.rows = {r.key: r for r in commands.itertuples(index=False)}
        self.descriptions: dict[str, str] = {}
        replaying = settings.replay is not None
        self.spend = Spend("mockllm/model" if replaying else settings.model)
        self.budget = JudgeBudget(cap_usd=settings.cap_usd, spent_fn=self.spend.summary,
                                  estimate_fn=worst_case(settings.model))
        self.misses: list[str] = []
        self.live = not settings.dry_run and not replaying and not settings.model.startswith("mockllm/")
        self.ledger = SpendLedger(settings.answers_dir / LEDGER_FILE) if self.live else None
        self.model = model or self._make_model()
        self._charge_failures(self.model)
        self.budget.guard(self.model)  # outermost: every attempt reserves its worst case first
        self.stop = False
        self.done = 0
        self.total = 0
        self.statuses: dict[str, int] = {}
        self.existing: dict[tuple[str, str], dict[str, Any]] = {}
        self._files: dict[str, Any] = {}
        self.started = time.monotonic()

    # -- models

    def _make_model(self) -> Any:
        from inspect_ai.model import get_model

        if self.s.replay:
            return replay_auditor(load_saved(self.s.answers_dir, self.s.replay), self.misses)
        if self.s.dry_run:
            return mock_auditor(self.s)
        if not self.s.model.startswith("mockllm/") and not self.s.live:
            raise SystemExit(f"refusing to call {self.s.model}: a real run needs --live (and the user's approval "
                             "of the spending cap). Use --dry-run to test for free.")
        # the provider's own client retries are off: the budget guard retries, each attempt with its own
        # reservation (and an attempt that may have been billed is charged, see _charge_failures)
        return get_model(self.s.model, **model_args(self.s.model))

    def _charge_failures(self, model: Any) -> None:
        """Charge the worst case for a failed attempt that may still have been billed (a time-out or a
        dropped connection: the provider may have done the work). Failures with an error reply from the
        provider are not billed and cost nothing here."""
        original = model.generate
        estimate = worst_case(self.s.model)

        async def generate(input: Any, *args: Any, **kwargs: Any) -> Any:
            truth = _TRUTH.get()
            if truth is not None:
                truth["attempts"] = truth.get("attempts", 0) + 1
            try:
                return await original(input, *args, **kwargs)
            except Exception as exc:
                if self.live and billing_unknown(exc):
                    usd, _ = estimate(model, input, kwargs.get("config"))
                    truth = _TRUTH.get() or {}
                    self.spend.add_unknown(usd or 0.0, truth.get("item", "unknown"))
                    if self.ledger is not None:
                        self.ledger.append({"batch": self.s.batch, "case_id": truth.get("case_id"),
                                            "version": truth.get("version"), "usd": usd,
                                            "kind": f"failed attempt, maybe billed ({type(exc).__name__})"})
                raise

        model.generate = generate

    def config(self) -> Any:
        from inspect_ai.model import GenerateConfig

        return GenerateConfig(**self.generation)

    @property
    def generation(self) -> dict[str, Any]:
        """The generation settings for the auditor model (a dry run uses the target model's, unused)."""
        return generation_settings(self.s.model, self.s.effort, self.s.max_tokens)

    # -- planning

    def description(self, run_id: str) -> str:
        if run_id not in self.descriptions:
            self.descriptions[run_id] = prompts.run_description(self.s.runs_dir / run_id)
        return self.descriptions[run_id]

    def plan(self) -> list[Job]:
        """Every job, in the order they are sent. ``random`` (the default): a random order fixed by the
        seed, so families and situations are interleaved and, if the cap stops the run early, the asks
        left over are a random sample rather than one block (say, one scenario's chains). Calls from one
        run still share their cached fixed part: with dozens of runs interleaved, each run is asked again
        well within the cache's five-minute lifetime. ``grouped``: run by run (for comparison)."""
        from swarmbench.studies.auditor.cases import DEFAULT_SEED, rng_for

        c = self.cases[self.cases["split"] == self.s.split]
        if self.s.situations:
            c = c[c["situation"].isin(self.s.situations)]
        asks = c.to_dict("records")
        if self.s.limit is not None:
            asks = _limit(asks, self.s.limit)
        jobs: list[Job] = []
        for v in self.s.versions:
            chains: dict[str, list[dict[str, Any]]] = {}
            for a in asks:
                a = dict(a)
                if a["situation"] == "chain" and a["variant"] == "main":
                    chains.setdefault(a["chain_id"], []).append(a)
                else:
                    jobs.append(Job("single", [a], v, "main"))
            for cid in sorted(chains):
                steps = sorted(chains[cid], key=lambda x: x["step"])
                jobs.append(Job("chain", steps, v, "main"))
            if self.s.split == "test" and (not self.s.situations or "queue" in self.s.situations) and len(self.queue):
                q = self.queue.to_dict("records")
                if self.s.limit is not None:
                    q = q[: max(1, self.s.limit // 10)]
                for m in q:
                    ask = {**m, "situation": "queue", "variant": "main", "key": None, "chain_id": None, "step": None}
                    jobs.append(Job("queue", [ask], v, "queue"))
        jobs.sort(key=lambda j: (j.asks[0]["run_id"], j.version, j.family, j.kind != "single", j.asks[0]["case_id"]))
        if self.s.order == "random":
            seed = int(asks[0].get("seed") or DEFAULT_SEED) if asks else DEFAULT_SEED
            order = rng_for(seed, f"ask-order-{self.s.split}-{','.join(self.s.versions)}").permutation(len(jobs))
            jobs = [jobs[int(i)] for i in order]
        return jobs

    # -- running

    async def run(self) -> dict[str, Any]:
        with self._live_lock():
            return await self._run()

    @contextlib.contextmanager
    def _live_lock(self) -> Any:
        """Only one real (paid) run at a time, so the study-wide cap can't be overrun by two processes."""
        if not self.live:
            yield
            return
        import fcntl

        self.s.answers_dir.mkdir(parents=True, exist_ok=True)
        protect = self.s.answers_dir / ".rm-protect"  # paid answers: deleting them needs the user's approval
        if not protect.exists():
            protect.touch()
        with (self.s.answers_dir / ".live.lock").open("w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SystemExit("another real auditor run is going; wait for it to finish") from exc
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    async def _run(self) -> dict[str, Any]:
        jobs = self.plan()
        self._open_files()
        self.existing = load_latest(self.s.answers_dir, self.s.batch) if self.s.resume else {}
        jobs = [j for j in (self._resume_job(j) for j in jobs) if j is not None]
        self.total = sum(len(j.asks) for j in jobs)
        warm: dict[tuple[str, str, str], asyncio.Event] = {}
        pending = list(jobs)

        async def worker() -> None:
            while pending:
                job = pending.pop(0)
                prefix = (job.asks[0]["run_id"], job.version, job.family)
                first = prefix not in warm
                if first:
                    warm[prefix] = asyncio.Event()
                else:
                    await warm[prefix].wait()  # its fixed part is stored by the run's first call
                await self.run_job(job, on_first=warm[prefix].set if first else None)

        try:
            await asyncio.gather(*(worker() for _ in range(max(1, self.s.workers))))
        finally:
            for f in self._files.values():
                f.close()
        return self.finish()

    def _resume_job(self, job: Job) -> Job | None:
        """The part of a job still to ask, given the batch's saved answers: by default, asks never asked or
        stopped by the cap; with ``retry_errors``, only asks whose call failed (and, in a chain, the steps
        after them). A chain restarts at that step, with the saved answers before it as its history."""
        if not self.existing:
            return None if self.s.retry_errors else job
        status = [(self.existing.get((a["case_id"], job.version)) or {}).get("status") for a in job.asks]
        if self.s.retry_errors:
            start = next((i for i, st in enumerate(status) if st == "error"), None)
        else:
            start = next((i for i, st in enumerate(status) if st in (None, "not_run")), None)
        if start is None or any(st != "answered" for st in status[:start]):
            return None
        if job.kind != "chain":
            return job
        job.past = [self.existing[(a["case_id"], job.version)]["raw"] or "" for a in job.asks[:start]]
        job.start = start
        return job

    async def run_job(self, job: Job, on_first: Any = None) -> None:
        def warmed() -> None:
            nonlocal on_first
            if on_first is not None:
                on_first()
                on_first = None

        try:
            if job.kind == "chain":
                answers: list[str] = list(job.past)
                chain_rows = [self.rows[a["key"]] for a in job.asks]
                after = None
                for i in range(job.start, len(job.asks)):
                    ask = job.asks[i]
                    if self.stop:
                        self.write_answer(ask, job.version, None, status="not_run",
                                          error="not asked: the spending cap was reached")
                        continue
                    if after is not None:
                        self.write_answer(ask, job.version, None, status="not_run_after_failure", error=after)
                        continue
                    raw = await self.ask(ask, job.version, past=answers, chain_rows=chain_rows[: i + 1],
                                         store=i < len(job.asks) - 1)
                    warmed()
                    if raw is None:
                        if not self.stop:
                            after = f"not asked: step {i} of this chain failed or was refused"
                        continue
                    answers.append(raw)
                return
            for ask in job.asks:
                if self.stop:
                    self.write_answer(ask, job.version, None, status="not_run",
                                      error="not asked: the spending cap was reached")
                    continue
                await self.ask(ask, job.version)
                warmed()
        finally:
            warmed()

    def build(self, ask: dict[str, Any], version: str, past: list[str] | None, chain_rows: list[Any] | None,
              store: bool = True) -> Any:
        desc = self.description(ask["run_id"])
        if ask["situation"] == "queue":
            return prompts.queue_request(ask, self.commands, desc, _queue_state(ask, self.queue_tools))
        return prompts.build_request(ask, self.rows, desc, version, past_answers=past or None, chain_rows=chain_rows,
                                     store=store)

    def truth(self, ask: dict[str, Any], version: str) -> dict[str, Any]:
        t: dict[str, Any] = {"case_id": ask["case_id"], "version": version, "item": item_of(ask), "attempts": 0}
        if ask["situation"] == "queue":
            t["queue"] = ask
            return t
        r = self.rows[ask["key"]]
        t.update(output=r.output, seconds=r.duration_s, exit_code=None if pd.isna(r.exit_code) else int(r.exit_code))
        if ask["situation"] == "shared":
            t["will_wait"] = bool(r.duration_s and not pd.isna(r.duration_s) and r.duration_s >= 30)
        return t

    async def ask(self, ask: dict[str, Any], version: str, past: list[str] | None = None,
                  chain_rows: list[Any] | None = None, store: bool = True) -> str | None:
        """Ask once, retrying a failed call or an unreadable answer up to MAX_RETRIES times in all (the
        pre-registered limit; the budget guard's own retries count towards it). The last readable answer
        is kept. Returns the raw answer, or None if every attempt failed or the cap stopped it."""
        from swarmbench.judge.budget import JudgeBudgetExhausted

        req = self.build(ask, version, past, chain_rows, store)
        messages = prompts.to_messages(req)
        rhash = request_hash(messages)
        self.write("requests", {"case_id": ask["case_id"], "instructions_version": version, "request_hash": rhash,
                                "messages": [{"role": m.role, "text": prompts_text(m),
                                              "cache": any(getattr(c, "cache_breakpoint", False) for c in m.content)}
                                             for m in messages]})
        truth = self.truth(ask, version)
        token = _TRUTH.set(truth)
        last_error: str | None = None
        best = None  # (raw, usage, cost, stop_reason) of the last readable answer, else of the last answer
        refused = None  # the latest attempt, when it was a refusal: (raw, usage, stop_reason, refusal)
        refusals = 0
        cost_total = 0.0
        try:
            while truth["attempts"] <= MAX_RETRIES:
                try:
                    out = await self.model.generate(messages, config=self.config())
                except JudgeBudgetExhausted as exc:
                    self.stop = True
                    if best is None:
                        self.write_answer(ask, version, None, status="not_run", rhash=rhash,
                                          error=f"not asked: the auditor's ${self.s.cap_usd:g} cap ({exc})")
                        return None
                    break
                except Exception as exc:
                    truth["attempts"] = max(truth["attempts"], 1)
                    last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                    continue
                truth["attempts"] = max(truth["attempts"], 1)
                cost = self.spend.add(out.usage, item_of(ask))
                cost_total += cost
                if self.ledger is not None:
                    self.ledger.append({"batch": self.s.batch, "case_id": ask["case_id"], "version": version,
                                        "usd": cost, "kind": "answer"})
                raw = out.completion or ""
                refusal = refusal_of(out)
                if refusal is not None:
                    # a refusal is asked again once (a classifier can clear on a second try), never more
                    refused = (raw, out.usage, getattr(out, "stop_reason", None), refusal)
                    refusals += 1
                    if refusals > 1:
                        break
                    continue
                refused = None
                readable = (prompts.parse_queue_answer(raw).parse_ok if ask["situation"] == "queue"
                            else prompts.parse_answer(raw).parse_ok)
                if readable or best is None or not best[4]:
                    best = (raw, out.usage, cost, getattr(out, "stop_reason", None), readable)
                if readable:
                    break
        finally:
            _TRUTH.reset(token)
        if refused is not None and (best is None or not best[4]):
            raw, usage, stop_reason, refusal = refused
            self.write_answer(ask, version, raw, status="refused", usage=usage, cost=cost_total, rhash=rhash,
                              stop_reason=stop_reason, attempts=truth["attempts"], refusal=refusal,
                              error=f"refused by the provider ({refusal['kind']})")
            return None
        if best is None:
            self.write_answer(ask, version, None, status="error", error=last_error or "no answer", rhash=rhash,
                              attempts=truth["attempts"], cost=cost_total)
            return None
        raw, usage, _, stop_reason, _ = best
        self.write_answer(ask, version, raw, status="answered", usage=usage, cost=cost_total, rhash=rhash,
                          stop_reason=stop_reason, attempts=truth["attempts"])
        return raw

    # -- writing

    def _open_files(self) -> None:
        d = self.s.answers_dir
        d.mkdir(parents=True, exist_ok=True)
        name = self.s.batch
        paths = {"answers": d / f"{name}.jsonl", "queue": d / f"{name}_queue.jsonl",
                 "requests": d / f"{name}_requests.jsonl"}
        for k, p in paths.items():
            self._files[k] = p.open("a" if self.s.resume else "w")  # resume appends; the latest line wins
        self.paths = {**paths, "summary": d / f"{name}_summary.json"}

    def write(self, which: str, record: dict[str, Any]) -> None:
        f = self._files[which]
        f.write(json.dumps(record, default=_json_default) + "\n")
        f.flush()

    def write_answer(self, ask: dict[str, Any], version: str, raw: str | None, *, status: str,
                     error: str | None = None, usage: Any = None, cost: float = 0.0, rhash: str | None = None,
                     stop_reason: Any = None, attempts: int = 0, refusal: dict[str, Any] | None = None) -> None:
        """One line per ask. ``status``: answered (score it; parse_ok says if it could be read), refused (the
        provider's safety filter or the model declined: reported as its own result, with ``refusal``), error
        (every attempt failed: a miss), not_run (the cap stopped it: left out and reported),
        not_run_after_failure (a chain step after a step that failed or was refused: left out and
        reported, so it can't look like drift)."""
        self.done += 1
        self.statuses[status] = self.statuses.get(status, 0) + 1
        common = {"case_id": ask["case_id"], "split": ask.get("split"), "situation": ask["situation"],
                  "variant": ask.get("variant"), "instructions_version": version, "model": self._model_name(),
                  "seed": ask.get("seed"), "draw_id": ask.get("draw_id"), "batch": self.s.batch,
                  "status": status, "raw": raw, "error": error, "attempts": attempts,
                  "retries": max(0, attempts - 1), "request_hash": rhash, "stop_reason": stop_reason,
                  "refusal": refusal, "generation": self.generation,
                  "cost_usd": cost, "usage": usage.model_dump(exclude_none=True) if usage is not None else None,
                  "time": datetime.now(UTC).isoformat()}
        answered = status == "answered"
        if ask["situation"] == "queue":
            q = prompts.parse_queue_answer(raw or "")
            self.write("queue", {**common, "run_id": ask["run_id"], "t_freeze": ask["t_freeze"],
                                 "typical_wait_s": q.typical_wait_s, "waiting_5min": q.waiting_5min,
                                 "waiting_10min": q.waiting_10min, "hits_limit": q.hits_limit,
                                 "parse_ok": q.parse_ok and answered})
        else:
            a = prompts.parse_answer(raw or "") if raw is not None else prompts.Answer(problems=["no answer"])
            self.write("answers", {**common, "key": ask["key"], "chain_id": ask.get("chain_id"),
                                   "step": None if ask.get("step") is None or pd.isna(ask.get("step")) else int(ask["step"]),
                                   "predicted_output": a.predicted_output, "predicted_exit_code": a.predicted_exit_code,
                                   "predicted_seconds": a.predicted_seconds, "predicted_low_s": a.predicted_low_s,
                                   "predicted_high_s": a.predicted_high_s, "predicted_never": a.predicted_never,
                                   "will_wait": a.will_wait, "parse_ok": a.parse_ok and answered,
                                   "parse_problems": a.problems})
        if not self.s.quiet and (self.done % 50 == 0 or self.done == self.total):
            print(f"  {self.done}/{self.total} asks, spent ${self.spend.usd:.2f} of ${self.s.cap_usd:g}"
                  f"{' (projected, nothing spent)' if self.s.dry_run else ''}, {self.statuses}", flush=True)

    def _model_name(self) -> str:
        if self.s.replay:
            return f"replay of {self.s.replay}"
        return "mockllm/model" if self.s.dry_run else self.s.model

    def finish(self) -> dict[str, Any]:
        errors = self.statuses.get("error", 0)
        summary = {
            "batch": self.s.batch, "split": self.s.split, "versions": self.s.versions, "model": self._model_name(),
            "priced_as": self.spend.price_model, "cap_usd": self.s.cap_usd, "dry_run": self.s.dry_run,
            "asks": self.total, "answered": self.statuses.get("answered", 0), "errors": errors,
            "statuses": self.statuses, "spent_usd": round(self.spend.usd, 4), "generation": self.generation,
            "cap_reached": self.stop or self.budget.hit, "by_item": self.spend.by_item,
            "replay_misses": self.misses,
            "settings": {k: str(v) if isinstance(v, Path) else v for k, v in asdict(self.s).items()},
            "seconds": round(time.monotonic() - self.started, 1),
        }
        self.paths["summary"].write_text(json.dumps(summary, indent=2, default=_json_default))
        return summary


def _json_default(v: Any) -> Any:
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if math.isnan(v) else float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, np.bool_):
        return bool(v)
    with contextlib.suppress(TypeError):
        if pd.isna(v):
            return None
    return str(v)


def _limit(asks: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """A small test slice: the first ``n`` single asks plus whole chains for up to ``n // 8`` chains."""
    singles = [a for a in asks if not (a["situation"] == "chain" and a["variant"] == "main")][:n]
    chain_ids = sorted({a["chain_id"] for a in asks if a["situation"] == "chain" and a["variant"] == "main"})
    keep = set(chain_ids[: max(1, n // 8)])
    return singles + [a for a in asks if a["situation"] == "chain" and a["variant"] == "main" and a["chain_id"] in keep]


def _queue_state(moment: dict[str, Any], tools: Any = None) -> dict[str, Any] | None:
    """What is running and waiting at a frozen moment, from the queue program; None (and the prompt
    goes without it) when the program can't say, e.g. the run's folder is missing."""
    if tools is None:
        from swarmbench.studies.auditor.cases import _queue_module

        tools = _queue_module()  # aud-yardsticks' queue_sim, when present
    fn = getattr(tools, "queue_state_at", None)
    if fn is None:
        return None
    try:
        return fn(moment["run_id"], pd.Timestamp(moment["t_freeze"]))
    except Exception:
        return None


def load_latest(answers_dir: Path, batch: str) -> dict[tuple[str, str], dict[str, Any]]:
    """(case_id, version) -> the latest saved line for that ask (files are appended to on resume)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for name in (f"{batch}.jsonl", f"{batch}_queue.jsonl"):
        p = answers_dir / name
        if p.exists():
            for line in p.read_text().splitlines():
                with contextlib.suppress(ValueError):
                    rec = json.loads(line)
                    out[(rec["case_id"], rec["instructions_version"])] = rec
    return out


def load_saved(answers_dir: Path, batch: str) -> dict[tuple[str, str], dict[str, Any]]:
    """(case_id, version) -> the saved answer line, from a batch's answers and queue files."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for name in (f"{batch}.jsonl", f"{batch}_queue.jsonl"):
        p = answers_dir / name
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    out[(rec["case_id"], rec["instructions_version"])] = rec
    if not out:
        raise SystemExit(f"no saved answers for batch {batch!r} in {answers_dir}")
    return out


# --- the cost projection ----------------------------------------------------------------------------------


def merge_items(summaries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for sm in summaries:
        for name, row in sm["by_item"].items():
            acc = out.setdefault(name, dict.fromkeys(row, 0))
            for k, v in row.items():
                acc[k] += v
    return out


def projection_table(items: dict[str, dict[str, float]], model: str = DEFAULT_MODEL, extra_thinking: int = 500) -> str:
    """The dry run's average cost per ask for each item, times the plan's number of calls for it, next
    to the plan's own figure. (A sample draw has fewer cases than the plan; the per-ask average is what
    carries over.)"""
    from swarmbench.costs import price_of

    lines = [f"{'item':48s} {'dry-run asks':>12s} {'per ask':>8s} {'calls':>10s} {'projected':>10s} {'plan rate':>9s}"]
    total = plan_total = 0.0
    calls_total = 0
    for name, (plan_calls, plan_usd) in PLAN_COSTS.items():
        row = items.get(name)
        plan_total += plan_usd
        if row and row["calls"]:
            per = row["usd"] / row["calls"]
            usd = per * plan_calls
            total += usd
            calls_total += plan_calls
            lines.append(f"{name:48s} {int(row['calls']):12d} {per:8.3f} {plan_calls:10d} {usd:10.2f} {plan_usd:9.2f}")
        elif name == "storing scenario descriptions":
            lines.append(f"{name:48s} {'':12s} {'':8s} {'':10s} {'in items':>10s} {plan_usd:9.2f}")
        else:
            lines.append(f"{name:48s} {0:12d} {'':8s} {plan_calls:10d} {'not run':>10s} {plan_usd:9.2f}")
    lines.append(f"{'total':48s} {'':12s} {'':8s} {calls_total:10d} {total:10.2f} {plan_total:9.2f}")
    per_think = extra_thinking * price_of(model).output / 1_000_000
    lines.append(f"If the auditor also thinks {extra_thinking} tokens per answer (Opus 5.5 always thinks some; effort "
                 f"sets how much): +${per_think:.3f} per call, +${per_think * calls_total:.2f} in total.")
    return "\n".join(lines)


def prior_spending(answers_dir: Path) -> float:
    """Dollars already charged by real runs (all batches), from the spending ledger."""
    return SpendLedger(answers_dir / LEDGER_FILE).total()


# --- command line ----------------------------------------------------------------------------------------


def load_keys() -> None:
    """API keys from a .env file in the current folder, as the `swarm` command loads them (tests set
    SWARMBENCH_NO_DOTENV so they never do)."""
    import os

    if not os.environ.get("SWARMBENCH_NO_DOTENV"):
        from inspect_ai._util.dotenv import init_dotenv

        init_dotenv()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ask the auditor about the drawn cases.")
    ap.add_argument("--batch", default=None, help="name for the saved files (default: from the split and mode)")
    ap.add_argument("--split", choices=["test", "practice", "all"], default="test",
                    help="all: practice (both versions) then test, for a full dry run")
    ap.add_argument("--versions", default=None, help="instruction versions, e.g. a,b (practice default: a,b)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--cap", type=float, default=DEFAULT_CAP_USD, help="hard dollar cap for the whole study")
    ap.add_argument("--overwrite", action="store_true",
                    help="start the batch's files afresh (refused for a batch with paid asks unless --force)")
    ap.add_argument("--force", action="store_true", help="with --overwrite: even a batch with paid asks")
    ap.add_argument("--retry-errors", action="store_true", help="re-ask only the asks whose calls failed")
    ap.add_argument("--order", choices=["random", "grouped"], default="random")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--max-tokens", type=int, default=None,
                    help=f"answer limit, reasoning included (default {MAX_ANSWER_TOKENS} for Anthropic, "
                         f"{MAX_ANSWER_TOKENS_REASONING} for others)")
    ap.add_argument("--effort", default=DEFAULT_EFFORT)
    ap.add_argument("--dry-run", action="store_true", help="use the mock model and project the cost")
    ap.add_argument("--mock-style", choices=["oracle", "noisy"], default="noisy")
    ap.add_argument("--assume-thinking-tokens", type=int, default=0)
    ap.add_argument("--replay", default=None, help="answer from this saved batch instead of a model")
    ap.add_argument("--live", action="store_true", help="allow calls to a real (paid) model")
    ap.add_argument("--limit", type=int, default=None, help="only a small slice of the cases (testing)")
    ap.add_argument("--situations", default=None, help="comma list: one_step,chain,shared,queue")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = ap.parse_args(argv)
    if args.live:
        load_keys()

    mode = "dryrun" if args.dry_run else ("replay" if args.replay else "live")
    if mode == "live" and not args.model.startswith("mockllm/") and not args.live:
        print(f"refusing to call {args.model}: a real run needs --live, after the user approves the cap. "
              "Use --dry-run to test for free.")
        return 2
    if args.split == "all" and mode != "dryrun":
        print("--split all is for dry runs; run the practice and test batches separately")
        return 2
    splits = ["practice", "test"] if args.split == "all" else [args.split]
    cases, queue = load_cases(args.data_dir)
    commands = load_commands(commands_path(args.data_dir))
    answers_dir = args.data_dir / "answers"
    summaries = []
    for split in splits:
        default_versions = "a,b" if split == "practice" else prompts.DEFAULT_VERSION
        versions = (args.versions if args.split != "all" else None) or default_versions
        slug = "" if args.model == DEFAULT_MODEL else "-" + args.model.rsplit("/", 1)[-1]
        batch = (args.batch if args.batch and args.split != "all"
                 else f"{split}{slug}" + ("" if mode == "live" else f"-{mode}"))
        paid = SpendLedger(answers_dir / LEDGER_FILE).batches()
        exists = (answers_dir / f"{batch}.jsonl").exists()
        if args.overwrite and batch in paid and not args.force:
            print(f"batch {batch} has paid asks in the spending ledger; --overwrite would lose them. "
                  "Pass --force as well if that is really meant.")
            return 2
        if mode == "dryrun" and exists and batch in paid:
            print(f"batch {batch} has paid asks; a dry run can't use its name")
            return 2
        # a real or replayed batch that exists already is resumed (appended to, done asks skipped);
        # a dry run starts afresh unless asked otherwise
        resume = exists and not args.overwrite and (mode != "dryrun" or args.retry_errors)
        if args.retry_errors and not exists:
            print(f"batch {batch} has no saved answers to retry")
            return 2
        prior = prior_spending(answers_dir) if mode == "live" else 0.0
        s = Settings(batch=batch, split=split, versions=versions.split(","), model=args.model,
                     cap_usd=args.cap - prior, max_tokens=args.max_tokens, effort=args.effort or None,
                     dry_run=args.dry_run, mock_style=args.mock_style,
                     assume_thinking_tokens=args.assume_thinking_tokens, replay=args.replay, live=args.live,
                     limit=args.limit, situations=args.situations.split(",") if args.situations else None,
                     data_dir=args.data_dir, order=args.order, workers=args.workers, resume=resume,
                     retry_errors=args.retry_errors)
        if s.cap_usd <= 0:
            print(f"the study's ${args.cap:g} cap is already spent (${prior:.2f} by earlier batches)")
            return 2
        run = AuditorRun(s, cases, queue, commands)
        print(f"batch {batch}: {split} split, versions {versions}, model {run._model_name()}, "
              f"cap ${s.cap_usd:.2f}{f' (${prior:.2f} already spent)' if prior else ''}"
              f"{', resuming' if resume else ''}{', retrying failed asks' if args.retry_errors else ''}")
        summary = asyncio.run(run.run())
        summaries.append(summary)
        print(f"done: {summary['statuses']}, "
              f"{'projected' if s.dry_run else 'spent'} ${summary['spent_usd']:.2f}"
              f"{' (cap reached)' if summary['cap_reached'] else ''}")
        if summary["replay_misses"]:
            print(f"replay: {len(summary['replay_misses'])} asks differed from or were missing in the saved batch")
        print("files:", ", ".join(str(p) for p in run.paths.values()))
    if args.dry_run:
        print(f"\nprojected cost at {args.model} prices, against the plan's cost table "
              f"(mock answers as long as the real outputs, plus {args.assume_thinking_tokens} thinking tokens):")
        print(projection_table(merge_items(summaries), args.model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
