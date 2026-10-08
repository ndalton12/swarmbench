"""Cost control for the two-pass judge (docs/judge-two-pass.md, "Cost control").

Before any model call:

1. **Projection.** The cost of every chunk review, of the reconciliation (with its
   tool rounds), of a possible repair round and of the summary, from the size of
   the compacted record and the prices in prices.yaml. Prompt caching is ignored,
   so the projection errs high (the judge asks for caching of the prompts every part and every
   tool round re-send). A repair round is held in reserve but not counted in the expected total.
2. **Hold-back.** The essential last steps (the reconciliation's final answer,
   one repair round, the summary) are held back from the cap: chunk reviews and
   discretionary tool rounds can't spend that part.
3. **Plan.** If the main judge model can review every chunk within what's left,
   it does. Otherwise chunks with no deterministic trigger are reviewed by the
   fallback model; chunks with a trigger, and the reconciliation, always use the
   main model. The plan, the projection and (later) the actual spend are saved
   in judge_trace.json.

A trigger is a fact in the record that calls for the strongest reader: a monitor
flag, a refused tool call, work through another agent's bridge, a message signed
as someone else, a tool call matching the monitor's risk rules, two different
results under one tool-call id, rewritten history, or a mention of a changed
file that lost lines.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from swarmbench.judge.chunks import Chunk
from swarmbench.judge.ledger import Ledger, call_arguments

CHARS_PER_TOKEN = 3.5
REVIEW_OUTPUT_TOKENS = 2_500
"""Expected answer of one chunk review (its cap is review.REVIEW_MAX_OUTPUT_TOKENS)."""
NOTE_CHARS_PER_CHUNK = 2 * REVIEW_OUTPUT_TOKENS * CHARS_PER_TOKEN
"""Notes appear in an agent's case file and in the team file or registers, so about twice."""
TOOL_ROUNDS = 4
"""Expected tool rounds in the reconciliation (its cap is reconcile.MAX_TOOL_ROUNDS)."""
TOOL_ROUND_CHARS = 6_000
FINAL_OUTPUT_TOKENS = 6_000
TOOL_ROUND_OUTPUT_TOKENS = 300
SUMMARY_INPUT_CHARS = 12_000
SUMMARY_OUTPUT_TOKENS = 1_500


def essential_max_tokens() -> tuple[int, int, int]:
    """The output allowance of the final answer, the repair round and the summary, as the
    calls are actually made (the reserve is computed from these)."""
    from swarmbench.judge.budget import JUDGE_MAX_OUTPUT_TOKENS
    from swarmbench.judge.reconcile import RECONCILE_MAX_OUTPUT_TOKENS

    return RECONCILE_MAX_OUTPUT_TOKENS, RECONCILE_MAX_OUTPUT_TOKENS, JUDGE_MAX_OUTPUT_TOKENS


def tokens(chars: float) -> int:
    return int(chars / CHARS_PER_TOKEN) + 1


@dataclass
class Call:
    what: str
    model: str
    input_tokens: int
    output_tokens: int
    usd: float | None
    expected: bool = True
    """False for a call kept in reserve only (the repair round, needed only if findings fail checks)."""


@dataclass
class Projection:
    main_model: str
    fallback_model: str
    cap_usd: float
    calls: list[Call] = field(default_factory=list)
    held_usd: float | None = None
    held_tokens: int = 0
    """The same reserve in tokens (the cap for models without a price)."""
    """Kept back from the cap for the reconciliation's final answer, a repair round and the summary."""
    plan: str = ""
    fallback_chunks: list[str] = field(default_factory=list)
    triggers: dict[str, list[str]] = field(default_factory=dict)
    main_only_usd: float | None = None
    """What the whole judging would cost with the main model reading everything."""
    over_cap: bool = False
    """Even the plan doesn't fit the cap: expect an incomplete, resumable judging."""

    @property
    def total_usd(self) -> float | None:
        """The expected cost: every call except those only held in reserve."""
        parts = [c.usd for c in self.calls if c.expected]
        return None if any(p is None for p in parts) else round(sum(parts), 4)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "total_usd": self.total_usd}


def _usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    from swarmbench.costs import price_of

    price = price_of(model)
    if price is None:
        return None
    return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


def _call(what: str, model: str, input_chars: float, output_tokens: int) -> Call:
    t_in = tokens(input_chars)
    return Call(what, model, t_in, output_tokens, _usd(model, t_in, output_tokens))


def chunk_triggers(ledger: Ledger, chunk: Chunk, workspace: Any) -> list[str]:
    """The deterministic reasons a chunk needs the main judge model (empty: none)."""
    from swarmbench.monitor.rules import pattern_hits, write_targets

    by_id = ledger.by_id()
    shrunk = [f.path for f in getattr(workspace, "files", []) if f.fragment and _net_removal(f.fragment)]
    reasons: list[str] = []

    def add(eid: str, why: str) -> None:
        reasons.append(f"{eid}: {why}")

    for eid in chunk.events:
        e = by_id[eid]
        if e.kind == "monitor":
            add(eid, "monitor flag")
        elif e.kind == "approval":
            add(eid, "refused tool call")
        elif e.kind == "context" and "rewritten" in ledger.text(e):
            add(eid, "rewritten history")
        elif e.kind == "message" and e.meta.get("claimed_sender") and e.meta["claimed_sender"] != e.actor:
            add(eid, "message signed as someone else")
        if e.owner and e.actor != e.owner and e.kind in ("text", "tool_call", "reasoning"):
            add(eid, f"{e.actor} acting through {e.owner}'s bridge")
        if e.meta.get("conflicts_with"):
            add(eid, "two different results under one tool-call id")
        if e.kind == "tool_call":
            args = call_arguments(ledger.text(e))
            hits = pattern_hits(args, e.meta.get("function"))
            if any(h.severity in ("medium", "high", "critical") for h in hits):
                add(eid, "risky tool call (" + "; ".join(h.summary for h in hits[:2]) + ")")
            written = write_targets(args, e.meta.get("function"))
            if shrunk and any(path.endswith(p) or p.endswith(path) for path in written for p in shrunk):
                add(eid, "writes a changed file that lost lines")
    return reasons


def _net_removal(diff: str) -> bool:
    lines = diff.splitlines()
    removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    return removed > added


def project(
    *,
    chunks: list[Chunk],
    chunk_chars: dict[str, int],
    review_system_chars: int,
    reconcile_fixed_chars: int,
    summary_extra_chars: int,
    main_model: str,
    fallback_model: str,
    cap_usd: float,
    triggers: dict[str, list[str]],
) -> Projection:
    """The projected cost of judging one sample, and the plan for who reads what.

    ``chunk_chars``: each chunk's rendered size; ``reconcile_fixed_chars``: the parts of
    the reconciliation prompt known before any review (system prompt, workspace changes,
    required checks); ``summary_extra_chars``: the summary's file excerpts and notes."""
    p = Projection(main_model=main_model, fallback_model=fallback_model, cap_usd=cap_usd, triggers=triggers)
    base = reconcile_fixed_chars + NOTE_CHARS_PER_CHUNK * len(chunks)
    final_round = base + TOOL_ROUNDS * TOOL_ROUND_CHARS
    essential = [
        _call("reconcile: final answer", main_model, final_round, FINAL_OUTPUT_TOKENS),
        Call(**{**_call("reconcile: one repair round", main_model,
                         final_round + FINAL_OUTPUT_TOKENS * CHARS_PER_TOKEN, FINAL_OUTPUT_TOKENS).__dict__,
                 "expected": False}),
        _call("summary", main_model, SUMMARY_INPUT_CHARS + summary_extra_chars, SUMMARY_OUTPUT_TOKENS),
    ]
    tool_rounds = [
        _call(f"reconcile: tool round {k + 1}", main_model, base + k * TOOL_ROUND_CHARS, TOOL_ROUND_OUTPUT_TOKENS)
        for k in range(TOOL_ROUNDS)
    ]
    # the reserve covers each essential call at its full output allowance, not its expected size
    worst = [_call(c.what, main_model, c.input_tokens * CHARS_PER_TOKEN, cap)
             for c, cap in zip(essential, essential_max_tokens(), strict=True)]
    held = [c.usd for c in worst]
    p.held_usd = None if any(h is None for h in held) else sum(held)  # type: ignore[arg-type]
    p.held_tokens = sum(c.input_tokens + c.output_tokens for c in worst)

    def reviews(model_for: dict[str, str]) -> list[Call]:
        return [_call(f"review {c.id}", model_for[c.id], review_system_chars + chunk_chars[c.id],
                      REVIEW_OUTPUT_TOKENS) for c in chunks]

    all_main = {c.id: main_model for c in chunks}
    main_reviews = reviews(all_main)
    p.main_only_usd = _sum([c for c in main_reviews + tool_rounds + essential if c.expected])
    available = None if p.held_usd is None else cap_usd - p.held_usd
    review_cost = _sum(main_reviews + tool_rounds)
    if available is None or review_cost is None or review_cost <= available:
        p.plan = "the main judge model reads every part" + (
            " (no prices: the token cap applies instead)" if available is None or review_cost is None else "")
        p.calls = main_reviews + tool_rounds + essential
        return p
    model_for = {c.id: (main_model if triggers.get(c.id) else fallback_model) for c in chunks}
    p.fallback_chunks = [c.id for c in chunks if model_for[c.id] == fallback_model]
    planned = reviews(model_for)
    p.calls = planned + tool_rounds + essential
    total_reviews = _sum(planned + tool_rounds)
    p.over_cap = total_reviews is not None and total_reviews > available
    p.plan = (
        f"a full pass by {main_model} would cost about ${p.main_only_usd:.2f}, over the "
        f"${cap_usd:.2f} cap with ${p.held_usd:.2f} held back for the final steps, so {fallback_model} reads "
        f"{len(p.fallback_chunks)} of {len(chunks)} parts that have no deterministic trigger"
        + ("; even so the projection is over the cap, so expect an incomplete, resumable judging"
           if p.over_cap else "")
    )
    return p


def _sum(calls: list[Call]) -> float | None:
    parts = [c.usd for c in calls]
    return None if any(p is None for p in parts) else sum(parts)  # type: ignore[arg-type]
