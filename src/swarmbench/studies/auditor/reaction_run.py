"""Sending the reaction test's requests to the agents' own models, and what that costs.

For every built case (``reaction.py build``) two requests go to the agent's own model, with the logged
call's tools, tool choice and generation settings: **A** (the auditor's predicted output in place of the
real one) and then **R** (the logged request unchanged). A goes first and R right after, so a provider
that caches prompt prefixes by itself (OpenAI, Gemini) can serve R's shared prefix from the cache.

Two ways to run:

- ``--dry-run``: Inspect's mock model answers every request with the logged answer (so A, R and L all
  agree and the scoring runs end to end), reporting the token counts the real call would have: the
  logged call's measured input tokens (exact for R; A adds the difference in the swapped text at the
  case's own characters-per-token rate) and its logged output tokens. Its usage is priced at the agent
  model's real prices, which gives the projected cost. Nothing is spent.
- a real run: needs ``--live``, after the user has approved the dollar cap.

**Two changes to the logged settings**, neither changing what the model sees: a request whose logged
settings set no output limit gets ``max_tokens`` = 32,000 (A and R alike; without a limit no call's cost
could be bounded), recorded on its answer line; and Inspect's per-sample provider state is rebuilt for
each request (below).

**Provider state.** Inspect keeps some wire-level detail outside the messages, per sample: for OpenAI's
Responses API, which earlier tool calls were "custom" (free-form) calls, and the namespace a call's tool
was declared in. Codex's ``exec`` is a custom tool and Codex declares its tools in a namespace; without
that record Inspect would send the earlier calls and results as plain function calls, unlike the real run.
So every request starts with fresh provider state, seeded with the custom and namespaced calls in its
history (``bind_provider_state``); ``custom_call_check`` confirms offline that the request then carries
them in that form. The item ids and statuses the real run also sent back are not in the log.

**Spending.** Before every attempt, its worst case is reserved with the judge's budget guard; an attempt
that doesn't fit under the cap is refused, so spending can't pass the cap. The worst case is a bound:
the logged call's measured input tokens (R is the same request, so the same count) plus, for A, one token
per byte of the swapped message, all plus a tenth and 500 tokens, at the dearer of the input and
cache-write prices; and the request's full output limit at the output price. The spend ledger
(``spend_ledger.jsonl`` in the reaction folder, separate from the auditor study's) gets a line reserving
the worst case before an attempt is sent and a line settling it to the real cost when the answer comes
back. An attempt that fails is settled to nothing only when the provider sent an error reply (an HTTP
status other than 408 or 504); any other failure (time-out, dropped connection, cancellation, a crash, an
error after the answer arrived, an answer that can't be priced) keeps its worst-case charge. The cap counts everything in the ledger,
read inside the lock that allows one real run at a time.

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
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from swarmbench.studies.auditor.runner import SpendLedger, _json_default, model_args, refusal_of

LEDGER_FILE = "spend_ledger.jsonl"
CONDITIONS = ("A", "R")
WORKERS = 8
MAX_OUTPUT_WHEN_UNSET = 32_000
"""The output limit given to a request whose logged settings set none."""
INPUT_MARGIN = 1.10
INPUT_SLACK_TOKENS = 500

_CALL: ContextVar[dict[str, Any] | None] = ContextVar("reaction_call", default=None)
"""What the call in flight is (case, condition, measured tokens), for the cap's worst case and the mock."""


# --- tokens and prices -----------------------------------------------------------------------------------


def provider_of(model: str) -> str:
    return model.split("/", 1)[0]


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


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


def _measured(row: dict[str, Any]) -> int | None:
    m = _num(row.get("logged_input_tokens"))
    return None if m is None else int(m)


def estimated_tokens(row: dict[str, Any], condition: str) -> int:
    """Expected input tokens of one request (for the projection): the logged call's measured count for R
    (the request is the same), and for A that count scaled by the change in length of the swapped text."""
    measured = _measured(row)
    r_chars = _num(row.get("r_chars")) or 0.0
    a_chars = _num(row.get("a_chars")) or r_chars
    if measured is None:
        measured = int(r_chars / 3.5)
    if condition == "R" or r_chars <= 0:
        return measured
    return max(1, round(measured * a_chars / r_chars))


def worst_input_tokens(row: dict[str, Any], condition: str) -> int:
    """A bound on one request's input tokens: the measured count (R is the logged request itself), plus for
    A one token per byte of the swapped message (no token is shorter than a byte, and the text it replaces
    counts at least nothing), plus a tenth and 500 tokens. Without a measured count: one token per byte of
    the whole request."""
    measured = _measured(row)
    base = measured if measured is not None else int(_num(row.get("r_bytes")) or 0)
    extra = int(_num(row.get("a_target_bytes")) or 0) if condition == "A" else 0
    return int((base + extra) * INPUT_MARGIN) + INPUT_SLACK_TOKENS


def output_limit(row_or_config: dict[str, Any]) -> int:
    """The request's output limit: the logged ``max_tokens``, else the one this test sets."""
    v = _num(row_or_config.get("max_tokens"))
    return MAX_OUTPUT_WHEN_UNSET if v is None else int(v)


def worst_case_usd(model: str, row: dict[str, Any], condition: str) -> float:
    from swarmbench.costs import price_of

    p = price_of(model)
    dear = max(p.input, p.input_cache_write or 0.0)
    return (worst_input_tokens(row, condition) * dear + output_limit(row) * p.output) / 1e6


def prefix_share(row: dict[str, Any]) -> float:
    """The share of the request before the swapped message (the part A and R have in common)."""
    share = _num(row.get("prefix_share"))
    return 0.9 if share is None else share


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
    logged_out = _num(row.get("logged_output_tokens"))
    out_tokens = int(output_tokens if output_tokens is not None else (1000 if logged_out is None else logged_out))
    a_in, r_in = estimated_tokens(row, "A"), estimated_tokens(row, "R")
    out_usd = 2 * out_tokens * p.output / 1e6
    if provider_of(model) == "anthropic":
        expected = (a_in + r_in) * write / 1e6 + out_usd
    else:
        shared = int(r_in * prefix_share(row))
        expected = (a_in * p.input + shared * read + (r_in - shared) * p.input) / 1e6 + out_usd
    no_cache = (a_in + r_in) * dear / 1e6 + out_usd
    worst = worst_case_usd(model, row, "A") + worst_case_usd(model, row, "R")
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


def effective_config(rec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """The logged generation settings, with an output limit added when they set none (and whether one was)."""
    config = dict(rec.get("config") or {})
    if _num(config.get("max_tokens")) is None:
        config["max_tokens"] = MAX_OUTPUT_WHEN_UNSET
        return config, True
    return config, False


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
    config = GenerateConfig.model_validate(effective_config(rec)[0])
    return messages, tools, tc, config


def request_hash(rec: dict[str, Any], condition: str) -> str:
    """A hash of exactly what is sent for one request (messages, tools, tool choice, settings, model)."""
    payload = json.dumps([rec.get("model"), rec[condition], rec.get("tools"), rec.get("tool_choice"),
                          effective_config(rec)[0]], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def tool_namespaces(tools: list[Any]) -> dict[str, str]:
    """Tool name -> the Responses API namespace it was declared in (Inspect's bridge keeps it in the tool's
    options; Codex declares its tools in one called "functions")."""
    from inspect_ai.model._openai_responses import RESPONSES_NAMESPACE

    out = {}
    for t in tools or []:
        options = getattr(t, "options", None) if not isinstance(t, dict) else t.get("options")
        ns = (options or {}).get(RESPONSES_NAMESPACE)
        if isinstance(ns, (list, tuple)) and len(ns) == 2:
            out[getattr(t, "name", None) if not isinstance(t, dict) else t.get("name")] = str(ns[0])
    return out


def history_tool_calls(messages: list[Any], tools: list[Any]) -> dict[str, dict[str, Any]]:
    """The earlier tool calls whose Responses API form doesn't survive in the messages, as the API takes
    them: custom (free-form) calls, and calls to tools declared in a namespace (with that namespace). In
    the real run Inspect cached these from the model's own answers and sent them back verbatim; the
    item ids and statuses it also kept are not in the log and are left out."""
    namespaces = tool_namespaces(tools)
    out: dict[str, dict[str, Any]] = {}
    for m in messages:
        for c in getattr(m, "tool_calls", None) or []:
            ns = namespaces.get(c.function)
            if getattr(c, "type", None) == "custom":
                param: dict[str, Any] = {"type": "custom_tool_call", "call_id": c.id, "name": c.function,
                                         "input": str((c.arguments or {}).get("input", ""))}
            elif ns:
                param = {"type": "function_call", "call_id": c.id, "name": c.function,
                         "arguments": json.dumps(c.arguments or {})}
            else:
                continue
            if ns:
                param["namespace"] = ns
            out[c.id] = param
    return out


def bind_provider_state(messages: list[Any], tools: list[Any] | None = None) -> int:
    """Fresh per-request provider state for Inspect (it is per sample, and this is no sample), seeded with
    the history's custom and namespaced tool calls so OpenAI's Responses API gets them back in their own
    form. Must run in the task that sends the request. Returns how many calls were seeded."""
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal

    init_sample_assistant_internal()
    calls = history_tool_calls(messages, tools or [])
    if calls:
        from inspect_ai.model._openai_responses import init_sample_openai_assistant_internal

        init_sample_openai_assistant_internal({"tool_calls": calls})
    return len(calls)


async def custom_call_check(rec: dict[str, Any], condition: str = "R") -> dict[str, Any]:
    """Offline: how Inspect would put this request to OpenAI's Responses API once the provider state is
    bound. Every earlier custom call must go as a custom call (its result as a custom output), and every
    earlier call to a namespaced tool with its namespace."""
    from inspect_ai.model._openai_responses import openai_responses_inputs

    messages, tools, _, _ = request_parts(rec, condition)
    seeded = history_tool_calls(messages, tools)
    bind_provider_state(messages, tools)
    items = await openai_responses_inputs(messages)
    by_id = {i.get("call_id"): i for i in items if i.get("type") in ("function_call", "custom_tool_call")}
    outputs = {i.get("call_id"): i for i in items if str(i.get("type", "")).endswith("_output")}
    wrong = 0
    for cid, want in seeded.items():
        got = by_id.get(cid) or {}
        if got.get("type") != want["type"] or got.get("namespace") != want.get("namespace"):
            wrong += 1
        out_type = "custom_tool_call_output" if want["type"] == "custom_tool_call" else "function_call_output"
        if cid in outputs and outputs[cid].get("type") != out_type:
            wrong += 1
    custom = sum(1 for v in seeded.values() if v["type"] == "custom_tool_call")
    return {"custom_calls": custom, "namespaced_calls": sum(1 for v in seeded.values() if v.get("namespace")),
            "sent_as_custom": sum(1 for i in items if i.get("type") == "custom_tool_call"),
            "wrong": wrong, "ok": wrong == 0}


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
        out_tokens = int(_num(row.get("logged_output_tokens")) or 0)
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
    """The cap's reservation for the attempt in flight (``JudgeBudget``'s estimate signature)."""

    def estimate(model: Any, input: Any, config: Any = None) -> tuple[float | None, int]:
        call = _CALL.get() or {}
        name = call.get("model") or str(model)
        row = {**(call.get("row") or {}), "max_tokens": call.get("max_tokens")}
        cond = call.get("condition", "R")
        return worst_case_usd(name, row, cond), worst_input_tokens(row, cond) + output_limit(row)

    return estimate


def billed_on_failure(exc: BaseException) -> bool:
    """Whether a failed attempt may still have been billed: anything but an error reply from the provider
    (an HTTP status other than 408 and 504, which may come after the work was done)."""
    for e in (exc, exc.__cause__, exc.__context__):
        code = getattr(e, "status_code", None)
        if isinstance(code, int) and 400 <= code < 600 and code not in (408, 504):
            return False
    return True


@dataclass
class RunSettings:
    batch: str
    out_dir: Path
    cap_usd: float
    """The cap for the whole reaction test: what the ledger already holds counts against it."""
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
    prior: float = 0.0
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
        self._mock = None
        if self.s.dry_run:
            self._mock = mock_model()
            self._account(self._mock, "mockllm/model")
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
            self._account(m, name)
            self.budget.guard(m)  # outermost: every attempt reserves its worst case before it is sent
            self.models[name] = m
        return self.models[name]

    def _account(self, model: Any, name: str) -> None:
        """Each attempt (the budget guard retries through here) reserves its worst case in the ledger before
        it is sent and settles it to the real cost when the answer comes back (see the module docstring)."""
        from swarmbench.costs import usage_cost

        original = model.generate
        estimate = worst_case_fn()

        async def generate(input: Any, *args: Any, **kwargs: Any) -> Any:
            call = _CALL.get() or {}
            call["attempts"] = call.get("attempts", 0) + 1
            priced = call.get("model") or name
            worst, _ = estimate(model, input, kwargs.get("config"))
            worst = float(worst or 0.0)
            attempt = uuid.uuid4().hex[:16]
            base = {"batch": self.s.batch, "case_id": call.get("case_id"), "condition": call.get("condition"),
                    "model": priced, "attempt": attempt}
            if self.ledger is not None:
                self.ledger.append({**base, "kind": "reserved", "usd": worst})
            try:
                out = await original(input, *args, **kwargs)
            except BaseException as exc:
                if billed_on_failure(exc):
                    self.spent += worst
                    call["usd"] = call.get("usd", 0.0) + worst
                    if self.ledger is not None:
                        self.ledger.append({**base, "kind": f"kept: failed attempt, maybe billed ({type(exc).__name__})",
                                            "usd": 0.0})
                elif self.ledger is not None:
                    self.ledger.append({**base, "kind": f"settled: error reply ({type(exc).__name__})",
                                        "usd": -worst})
                raise
            try:
                usd = float(usage_cost({priced: out.usage}).usd or 0.0) if out.usage is not None else worst
                kind = "settled" if out.usage is not None else "kept: no usage reported"
            except Exception as exc:  # the answer was billed but can't be priced: keep its worst case
                usd, kind = worst, f"kept: could not price ({type(exc).__name__})"
            self.spent += usd
            call["usd"] = call.get("usd", 0.0) + usd
            if self.ledger is not None:
                self.ledger.append({**base, "kind": kind, "usd": usd - worst, "cost": usd})
            return out

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
            if self.ledger is not None:
                # read inside the lock, so no other real run can spend between this read and this run's calls
                self.prior = self.ledger.total()
                self.budget.cap_usd = self.s.cap_usd - self.prior
                if self.budget.cap_usd <= 0:
                    return {"batch": self.s.batch, "cap_usd": self.s.cap_usd, "prior_usd": round(self.prior, 4),
                            "error": "the cap is already spent", "statuses": {}}
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
                   "prior_usd": round(self.prior, 4), "cap_usd": self.s.cap_usd,
                   "cap_reached": self.stop or self.budget.hit,
                   "seconds": round(time.monotonic() - started, 1), "answers": str(path),
                   "time": datetime.now(UTC).isoformat()}
        (self.s.answers_dir / f"{self.s.batch}_summary.json").write_text(json.dumps(summary, indent=2))
        return summary

    async def ask(self, row: dict[str, Any], rec: dict[str, Any], condition: str) -> dict[str, Any]:
        from swarmbench.judge.budget import JudgeBudgetExhausted

        name = rec["model"]
        config, limit_added = effective_config(rec)
        base = {"case_id": row["case_id"], "condition": condition, "model": name, "batch": self.s.batch,
                "request_hash": request_hash(rec, condition), "dry_run": self.s.dry_run,
                "max_tokens_added": limit_added}
        if self.stop:
            return self._line(base, "not_run", error="not asked: the spending cap was reached")
        messages, tools, tool_choice, gen_config = request_parts(rec, condition)
        call = {"case_id": row["case_id"], "condition": condition, "model": name, "row": row,
                "max_tokens": config["max_tokens"], "logged_output": rec.get("logged_output"), "attempts": 0,
                "usd": 0.0}
        token = _CALL.set(call)
        refusals = 0
        try:
            while True:
                base["history_calls_seeded"] = bind_provider_state(messages, tools)
                try:
                    out = await self.model(name).generate(messages, tools=tools, tool_choice=tool_choice,
                                                          config=gen_config)
                except JudgeBudgetExhausted as exc:
                    self.stop = True
                    return self._line(base, "not_run", error=f"not asked: the cap ({exc})",
                                      attempts=call["attempts"], usd=call["usd"])
                except Exception as exc:
                    return self._line(base, "error", error=f"{type(exc).__name__}: {str(exc)[:500]}",
                                      attempts=call["attempts"], usd=call["usd"])
                refusal = refusal_of(out)
                if refusal is not None and refusals == 0:
                    refusals += 1  # a refusal is asked once more (a classifier can clear on a second try)
                    continue
                status = "refused" if refusal is not None else "answered"
                return self._line(base, status, output=out.model_dump(mode="json", exclude_none=True),
                                  stop_reason=getattr(out, "stop_reason", None), refusal=refusal,
                                  usage=out.usage.model_dump(exclude_none=True) if out.usage else None,
                                  usd=call["usd"], attempts=call["attempts"], refusals=refusals)
        finally:
            _CALL.reset(token)

    def _line(self, base: dict[str, Any], status: str, **extra: Any) -> dict[str, Any]:
        self.statuses[status] = self.statuses.get(status, 0) + 1
        done = sum(self.statuses.values())
        if not self.s.quiet and done % 20 == 0:
            print(f"  {done} requests, {'projected' if self.s.dry_run else 'spent'} ${self.spent:.2f} "
                  f"(cap ${self.s.cap_usd:g}, ${self.prior:.2f} spent before), {self.statuses}", flush=True)
        return {**base, "status": status, "time": datetime.now(UTC).isoformat(), **extra}


def prior_spending(out_dir: Path) -> float:
    return SpendLedger(out_dir / LEDGER_FILE).total()


def load_answers(out_dir: Path, batch: str) -> pd.DataFrame:
    path = out_dir / "answers" / f"{batch}.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return pd.DataFrame(rows)
