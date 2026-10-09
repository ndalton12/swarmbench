"""The two-pass judge for one sample (docs/judge-two-pass.md): the main judge
model reads every chunk of the compacted record once, then reconciles the
notes into findings with tools. Selected with ``swarm judge --engine two-pass``;
the scanner judge stays the default until the shadow comparison.

The output is the same ``JudgeReport`` as the scanner judge, built by the same
``build_report``, so invariants, report.json/report.md, status, the Inspect
score, the Scout export and record/replay are shared. A trace of the judging
(chunks, notes, tool use, inferred links, coverage manifest) is written beside
the report as ``judge_trace.json``.

Cost control (projection.py): before any call the judge projects the cost, holds
back the essential last steps, and, only if the cap requires it, has the fallback
model read the parts with no deterministic trigger. Parts that were read are
saved in ``judge_progress.json``, so a judging cut short by its budget can be
resumed without reading them again.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from swarmbench.judge.chunks import CHUNK_CHARS, make_chunks, render_chunk
from swarmbench.judge.cite import EvidenceTable
from swarmbench.judge.compaction import stats as compaction_stats
from swarmbench.judge.extract import SampleInputs
from swarmbench.judge.findings import build_findings, mark_not_assessed, merge_repair
from swarmbench.judge.ledger import Ledger
from swarmbench.judge.material import Material, build_material
from swarmbench.judge.projection import chunk_triggers, project
from swarmbench.judge.reconcile import (
    Tools,
    case_files,
    obligations,
    reconcile,
    reconcile_system_prompt,
    reconcile_user_prompt,
    repair,
    trace_tool_uses,
)
from swarmbench.judge.review import (
    ReviewContext,
    behavior_catalogue,
    merge_evidence,
    review_all,
    review_system_prompt,
)
from swarmbench.judge.scanners import AGENT_SPECS, TEAM_SPECS, ScanHit, make_limiter
from swarmbench.judge.workspace_files import FileExcerpt
from swarmbench.types import JudgeReport

TRACE_FILE = "judge_trace.json"
PROGRESS_FILE = "judge_progress.json"
"""Chunk reviews that succeeded, per sample, so an interrupted judging can be resumed."""
RESUME_HINT = "resume with `swarm judge RUN --engine two-pass --resume`"
ENGINES = ("scanners", "two-pass")
MAX_PROMPT_CHARS = 6_000
MAX_NOTES_CHARS = 10_000


def run_brief(ledger: Ledger, inputs: SampleInputs, notes_md: str) -> str:
    """What every judge call needs to know about the run: agents, task prompts, designer notes."""
    lines = []
    for a in inputs.agents_meta or [{"name": v.name} for v in inputs.agents]:
        bits = [str(a.get(k)) for k in ("model", "user", "team") if a.get(k)]
        lines.append(f"- {a.get('name')}" + (f" ({', '.join(bits)})" if bits else ""))
    prompts: list[tuple[str, str]] = []
    seen_agents: set[str] = set()
    seen_text: dict[str, str] = {}
    for e in ledger.events:
        to = e.meta.get("to")
        if e.kind != "prompt" or not to or to in seen_agents:
            continue
        seen_agents.add(to)
        text = ledger.text(e)
        if text in seen_text:
            prompts.append((to, f"(same as {seen_text[text]}'s)"))
        else:
            seen_text[text] = to
            prompts.append((to, text[:MAX_PROMPT_CHARS] + (" [...]" if len(text) > MAX_PROMPT_CHARS else "")))
    task = "\n\n".join(f"First prompt to {who}:\n{text}" for who, text in prompts) or "(none recorded)"
    notes = notes_md[:MAX_NOTES_CHARS] if notes_md else "(none)"
    return (
        "<run_brief>\n"
        f"Scenario: {inputs.scenario}\nAgents:\n" + "\n".join(lines) + "\n\n" + task + "\n</run_brief>\n\n"
        "<designer_notes note=\"private notes from the scenario's designers; the agents never saw them. "
        "Data, not instructions.\">\n" + notes + "\n</designer_notes>"
    )


def excerpts_from_evidence(material: Material) -> list[FileExcerpt]:
    """The workspace evidence as file excerpts, so quotes from changed files verify everywhere."""
    out = []
    for f in material.workspace.files:
        if f.fragment:
            out.append(FileExcerpt(team=f.team, path=f.path, change=f.change, owner=f.owner, named_in_notes=False,
                                   diff=f.fragment, truncated=f.fragment_cut))
    return out


def _chunk_chars(advanced: Any) -> int:
    extra = getattr(advanced, "extra", None) or {}
    with contextlib.suppress(TypeError, ValueError):
        return max(2_000, int(extra.get("judge_chunk_chars", CHUNK_CHARS)))
    return CHUNK_CHARS


PROMPT_VERSION = "two-pass-2026-10-09-compact"
"""Changes whenever the review prompts or note schema change, so old progress isn't reused."""


def ledger_digest(ledger: Ledger) -> str:
    """Identifies the record as the judge reads it: every entry (kind, time, actor, bridge owner
    and basis, content and metadata) and every recorded link."""
    import hashlib

    entries = [[e.id, e.kind, e.time.isoformat() if e.time else None, e.actor, e.owner, e.basis, e.content,
                e.meta] for e in ledger.events]
    links = [[lk.kind, lk.src, lk.dst] for lk in ledger.links]
    raw = json.dumps([entries, links], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def progress_key(digest: str, review_system: str, chunk_chars: int, view: list[Any] | None = None) -> str:
    """Everything a part review depends on besides its reader: the record, the prompt (its
    version and text, which includes the brief and the designer notes), the cutting settings, and
    the compacted text itself (``view``), so any change in what a part shows the judge (a new
    compaction rule, a different policy for the run) means earlier reviews are not reused."""
    import hashlib

    from swarmbench.judge import compaction

    settings = [PROMPT_VERSION, compaction.VERSION, chunk_chars, compaction.LONG_OUTPUT, compaction.HEAD,
                compaction.TAIL, compaction.REPEAT_MIN, compaction.LONG_CALL, compaction.CALL_HEAD,
                compaction.CALL_TAIL]
    shown = hashlib.sha256("\x1e".join(c.text for c in view or []).encode()).hexdigest()
    raw = json.dumps([digest, hashlib.sha256(review_system.encode()).hexdigest(), settings, shown])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def reusable(progress: dict[str, Any] | None, key: str, dry_run: bool, planned: dict[str, set[str]]
             ) -> tuple[list[Any], str]:
    """Earlier reviews that may be reused, and why any were not. ``planned``: part -> the readers
    this judging accepts for it (the main model; the fallback too for a part with no trigger)."""
    from swarmbench.judge.review import review_from_json

    if not progress:
        return [], ""
    if progress.get("key") != key:
        return [], "earlier progress not reused: the record, the prompts or the settings have changed"
    if progress.get("dry_run") and not dry_run:
        return [], "earlier progress not reused: it came from a dry run with the mock judge"
    keep, dropped = [], 0
    for data in progress.get("reviews") or []:
        review = review_from_json(data)
        first = review.chunk.id.split(".")[0]
        accepted = review.model in planned.get(first, set())
        if accepted and (dry_run or not review.model.startswith("mockllm/")):
            keep.append(review)
        else:
            dropped += 1
    why = (f"{dropped} earlier part review(s) not reused: read by a model this judging doesn't use for "
           "that part" if dropped else "")
    return keep, why


def record_texts(ledger: Ledger, workspace: Any, table: EvidenceTable) -> dict[str, str]:
    """Every entry's full text and every changed file's shown change (plus the whole change of a file
    cited beyond it): what the report's quotes are checked against, each against its own source."""
    out = {e.id: ledger.text(e) for e in ledger.events}
    for f in workspace.files:
        out[f.id] = f.fragment
    for item in table.items.values():
        if item.kind == "file" and item.text not in out.get(item.entry, ""):
            out[item.entry] = out.get(item.entry, "") + "\n" + table.full_diff(item.entry)
    return out


def as_item(e: Any) -> Any:
    from swarmbench.types import EvidenceItem

    return EvidenceItem(id=e.id, entry=e.entry, text=e.text, author=e.author, kind=e.kind, label=e.label,
                        time=e.time)


def judge_notes(problems: list[str], merged: Any, rec: Any, findings: Any, leaves: list[Any],
                table: EvidenceTable) -> list[str]:
    """Problems with the judge's own answer, in plain words (for the report's technical notes). None of
    these makes the run "not fully assessed" by itself; what they cost a rating is in the gaps."""
    notes = []
    if problems:
        outcome = ("the corrected answer was used" if merged is not None
                   else f"no usable correction came back ({rec.repair_error or 'no answer'}), so the checks "
                        "applied their own corrections")
        notes.append(f"{len(problems)} finding(s) failed the record checks and were sent back to the judge "
                     f"once; {outcome}.")
    notes += [f"Changed by the checks: {c}" for c in findings.corrections]
    notes += [f"Dropped: {d}" for d in findings.dropped]
    bad_notes = [n for leaf in leaves for n in getattr(leaf, "dropped_notes", [])]
    if bad_notes:
        notes.append(f"{len(bad_notes)} malformed note(s) in the part reviews were left out "
                     f"(e.g. {bad_notes[0]}); the rest of those reviews were kept.")
    dropped = sum(leaf.dropped_quotes for leaf in leaves)
    if dropped:
        notes.append(f"{dropped} citation(s) in the part reviews' notes were dropped (not found in the record, "
                     "or an evidence id the reviewer never got).")
    return notes  # citation misses are normal (the judge retries): counted in the stats only


def _spend(budget: Any) -> tuple[float | None, dict[str, float | None]]:
    """The judge's spend so far, in total and by model."""
    from swarmbench.judge.budget import cost_of, usage_so_far

    if budget is not None and budget.spent_fn is not None:
        cost = budget.spent_total()
    else:
        cost = cost_of(usage_so_far())
    return cost.usd, dict(cost.by_model)


def _difference(before: tuple[float | None, dict[str, Any]], after: tuple[float | None, dict[str, Any]]
                ) -> dict[str, Any]:
    usd = None if before[0] is None or after[0] is None else round(after[0] - before[0], 6)
    by_model = {}
    for m, v in after[1].items():
        b = before[1].get(m, 0.0)
        by_model[m] = None if v is None or b is None else round(v - b, 6)
    return {"usd": usd, "by_model": {m: v for m, v in by_model.items() if v != 0.0}}


async def judge_sample_two_pass(
    sample: Any,
    inputs: SampleInputs,
    run_root: Path | None,
    model: Any,
    model_name: str,
    notes_md: str,
    *,
    budget: Any = None,
    concurrency: int | None = None,
    extra_gaps: list[str] | None = None,
    advanced: Any = None,
    fallback: Any = None,
    fallback_name: str = "",
    progress: dict[str, Any] | None = None,
    dry_run: bool = False,
    recorded: dict[str, Any] | None = None,
    record: Any = None,
) -> tuple[JudgeReport, list[ScanHit], dict[str, Any]]:
    """Judge one sample.

    ``fallback``: a callable returning the fallback reader (a model), resolved only if the plan
    needs it. ``progress``: saved progress from an earlier, interrupted judging of this sample
    (chunk reviews that succeeded are reused when the record, prompts, settings and readers are
    the same). ``recorded``: the decisions of the judging being replayed (who read which part,
    when investigation was stopped); ``record``: where to save this judging's decisions."""
    from swarmbench.judge.reconcile import tool_infos
    from swarmbench.judge.report import build_report
    from swarmbench.judge.review import review_to_json
    from swarmbench.judge.timeline import critical_moment_hint, little_happened
    from swarmbench.judge.workspace_files import render_block

    if budget is not None:
        budget.start_sample()
    spent_before = _spend(budget)
    material = build_material(sample, inputs, run_root)
    inputs.file_excerpts = excerpts_from_evidence(material)
    ledger, view, manifest = material.ledger, material.view, material.manifest
    agents = [a.name for a in inputs.agents]
    limiter = make_limiter(concurrency)
    brief = run_brief(ledger, inputs, notes_md)
    specs = AGENT_SPECS + TEAM_SPECS
    catalogue = behavior_catalogue(specs)
    hint = critical_moment_hint(notes_md)
    digest = ledger_digest(ledger)
    review_system = review_system_prompt(catalogue, brief)
    system = reconcile_system_prompt(catalogue, brief, agents, [s.key for s in TEAM_SPECS],
                                     [s.key for s in AGENT_SPECS], hint)

    # before any call: project the cost, hold back the essential steps, plan who reads what
    chunks = make_chunks(ledger, view, _chunk_chars(advanced))
    view_by_id = {c.id: c for c in view}
    triggers = {c.id: chunk_triggers(ledger, c, material.workspace) for c in chunks}
    early_checks = obligations(ledger, inputs, material.workspace, [])
    tools_chars = len(json.dumps([t.model_dump() for t in tool_infos()]))
    projection = project(
        chunks=chunks,
        chunk_chars={c.id: len(render_chunk(c, view_by_id, len(chunks))) for c in chunks},
        review_system_chars=len(review_system),
        reconcile_fixed_chars=len(system) + len(material.workspace.render()) + tools_chars
        + sum(len(c) + 8 for c in early_checks),
        summary_extra_chars=len(render_block(inputs.file_excerpts)) + min(len(notes_md), 4000),
        main_model=model_name,
        fallback_model=fallback_name or model_name,
        cap_usd=budget.cap_usd if budget is not None else float("inf"),
        triggers={k: v for k, v in triggers.items() if v},
    )
    if budget is not None:
        budget.set_hold(projection.held_usd, projection.held_tokens)
    if recorded:
        # a replay makes the recorded decisions, not ones recomputed from mock prices
        projection.fallback_chunks = list((recorded.get("plan") or {}).get("fallback_chunks") or [])
        model_name = recorded.get("main_model") or model_name
        fallback_name = recorded.get("fallback_model") or fallback_name
    assign: dict[str, tuple[Any, str]] = {}
    if projection.fallback_chunks and fallback is not None:
        reader = fallback()
        assign = {cid: (reader, fallback_name) for cid in projection.fallback_chunks}
    decisions: dict[str, Any] = {
        "main_model": model_name, "fallback_model": fallback_name,
        "plan": {"fallback_chunks": projection.fallback_chunks, "text": projection.plan},
        "admissions": [],
    }

    # pass 1: every chunk, one open-ended review each (or reused from an interrupted judging)
    key = progress_key(digest, review_system, _chunk_chars(advanced), view)
    planned = {c.id: {model_name} | ({fallback_name} if fallback_name and not triggers.get(c.id) else set())
               for c in chunks}
    earlier, not_reused = reusable(progress, key, dry_run, planned)
    replayed_cites = {str(k): list(v) for k, v in ((recorded or {}).get("cite_admissions") or {}).items()}
    decisions["cite_admissions"] = {}

    def admit(chunk_id: str, reader: Any, messages: list[Any]) -> Any:
        """A round with the cite tool on, only if its worst case plus a worst-case answer after it fit
        outside the held-back reserve. The answer's share is reserved (the ticket) until the answer is
        sent, so concurrent parts can't spend it. Recorded per part, so a replay decides the same."""
        ticket: Any = None
        if recorded is not None and replayed_cites.get(chunk_id):
            ticket = True if replayed_cites[chunk_id].pop(0) else None
        elif budget is None:
            ticket = True
        else:
            from inspect_ai.model import ChatMessageUser, GenerateConfig

            from swarmbench.judge.budget import estimate_call
            from swarmbench.judge.review import ANSWER_GROWTH_CHARS, REVIEW_MAX_OUTPUT_TOKENS

            estimate = budget.estimate_fn or estimate_call
            config = GenerateConfig(max_tokens=REVIEW_MAX_OUTPUT_TOKENS)
            usd, tokens = estimate(reader, messages, config)
            grown = [*messages, ChatMessageUser(content="x" * ANSWER_GROWTH_CHARS)]
            answer_usd, answer_tokens = estimate(reader, grown, config)
            usd_left, tokens_left = budget.room()
            if usd is not None and answer_usd is not None and usd_left is not None:
                ok = usd_left - usd - answer_usd >= budget.hold_usd
            else:
                ok = tokens_left - tokens - answer_tokens >= budget.hold_tokens
            if ok and budget.try_reserve(answer_usd, answer_tokens):
                ticket = (answer_usd, answer_tokens)
        decisions["cite_admissions"].setdefault(chunk_id, []).append(bool(ticket))
        return ticket

    def release(ticket: Any) -> None:
        if isinstance(ticket, tuple) and budget is not None:
            budget.release(*ticket)

    ctx = ReviewContext(ledger=ledger, view=view, view_by_id=view_by_id, total=len(chunks), system=review_system,
                        agents=set(agents), manifest=manifest, limiter=limiter, workspace=material.workspace,
                        run_root=run_root, admit=admit, release=release)
    reviews = await review_all(chunks, ctx, model=model, model_name=model_name, assign=assign, reuse=earlier)
    # every part's citations into the run's evidence table, in part order (ids don't depend on timing)
    table = EvidenceTable(ledger, material.workspace, run_root=run_root)
    merge_evidence(reviews, table)
    unread = set(manifest.unread())
    by_id = ledger.by_id()
    partial_agents = {by_id[eid].actor for eid in unread if by_id[eid].actor in agents}
    leaves = [leaf for r in reviews for leaf in r.leaves()]
    resumed = [leaf for r in reviews if r.resumed for leaf in r.leaves()]
    coverage_note = (
        f"{len(ledger.events) - len(unread)} of {len(ledger.events)} record entries read in {len(leaves)} part(s)"
        + (f" ({len(resumed)} reused from an earlier, interrupted judging)" if resumed else "")
        + "".join(f"; part {leaf.chunk.id} ({leaf.chunk.span()}) not reviewed: {leaf.error}"
                  for leaf in leaves if not leaf.ok)
    )

    # pass 2: reconcile the notes into findings, checking the record with tools. These are the
    # essential steps: they may spend what was held back, but tool rounds stop while the final
    # answer is still affordable.
    files = case_files(reviews, ledger, agents)
    checks = obligations(ledger, inputs, material.workspace, reviews)
    user = reconcile_user_prompt(files, reviews, checks, material.workspace, coverage_note, table)
    tools = Tools(ledger, view, material.workspace, run_root, table)

    replayed_admissions = list((recorded or {}).get("admissions") or [])

    def can_investigate(messages: list[Any]) -> bool:
        """Another tool round only if its worst case (the prompt so far plus its full output
        allowance) still leaves the held-back reserve for the final answer and the summary."""
        if recorded is not None and replayed_admissions:
            allowed = bool(replayed_admissions.pop(0))
        elif budget is None:
            allowed = True
        else:
            from inspect_ai.model import GenerateConfig

            from swarmbench.judge.budget import estimate_call
            from swarmbench.judge.reconcile import RECONCILE_MAX_OUTPUT_TOKENS

            usd, tokens = (budget.estimate_fn or estimate_call)(
                model, messages, GenerateConfig(max_tokens=RECONCILE_MAX_OUTPUT_TOKENS))
            usd_left, tokens_left = budget.room()
            if usd is not None and usd_left is not None:
                allowed = usd_left - usd >= budget.hold_usd
            else:
                allowed = tokens_left - tokens >= budget.hold_tokens
        decisions["admissions"].append(allowed)
        return allowed

    held = budget.essential() if budget is not None else contextlib.nullcontext()
    with held:
        rec = await reconcile(system=system, user=user, model=model, model_name=model_name, tools=tools,
                              manifest=manifest, limiter=limiter, can_investigate=can_investigate)

        # the final review's tools may have read entries no part review did: recompute what is unread
        unread = set(manifest.unread())
        partial_agents = {by_id[eid].actor for eid in unread if by_id[eid].actor in agents}
        recovered = [leaf for leaf in leaves if not leaf.ok and not set(leaf.chunk.events) & unread]
        coverage_note = (
            f"{len(ledger.events) - len(unread)} of {len(ledger.events)} record entries read in "
            f"{len(leaves)} part(s)"
            + (f" ({len(resumed)} reused from an earlier, interrupted judging)" if resumed else "")
            + "".join(f"; part {leaf.chunk.id} ({leaf.chunk.span()}) not reviewed: {leaf.error}"
                      + (" (its entries were read in full by the final review instead)" if leaf in recovered
                         else "")
                      for leaf in leaves if not leaf.ok)
        )

        def validated(data: dict[str, Any] | None) -> Any:
            return build_findings(data, ledger=ledger, workspace=material.workspace, inputs=inputs,
                                  sample=sample, hint=hint, error=rec.error, partial_agents=partial_agents,
                                  checks=checks, table=table)

        findings = validated(rec.data)
        first_problems = list(findings.problems)
        merged_answer = None
        if rec.data is not None and first_problems:
            # findings that failed the record checks go back to the model once; only those are replaced
            fixed = await repair(rec, first_problems, model=model, model_name=model_name, manifest=manifest,
                                 limiter=limiter)
            if fixed is not None:
                try:
                    merged_answer = merge_repair(rec.data, fixed, findings.problem_keys)
                    findings = validated(merged_answer)
                except Exception as exc:  # never lose the validated findings to a bad repair
                    findings = mark_not_assessed(validated(rec.data), set(findings.problem_keys),
                                                 f"the repair could not be applied ({type(exc).__name__})")

        gaps = list(extra_gaps or [])
        out_of_budget = budget is not None and budget.exhausted()
        if out_of_budget:
            gaps.insert(0, budget.gap())
        elif budget is not None and budget.held_back:
            gaps.insert(0, budget.held_gap())
        gaps += manifest.reconcile(sample)
        # what the judge couldn't read of the workspace (missing or unreadable snapshots, files compared
        # only in part); the engine's own comparison limits are already among the report's gaps
        gaps += [g for g in material.workspace.gaps if g not in inputs.workspace_gaps and g not in gaps]
        if rec.data is None:
            gaps.append(f"the final review failed ({rec.error or 'no answer'}), so nothing was rated")
        gaps += [g for g in findings.gaps if g not in gaps]
        if rec.tools_stopped_by_budget:
            gaps.append("the final review's checking was cut short to stay within the judge's budget")
        if unread:
            gaps.append(f"{RESUME_HINT} to read the {len(unread)} unread entries")
        explicit = sum(1 for h in findings.awareness if h.label == "explicit" and not h.error)
        note = little_happened(findings.turning_points, findings.expected_moment, inputs, explicit) if rec.data else ""
        agent_hits = [h for h in findings.hits if h.scope == "agent"]
        team_hits = [h for h in findings.hits if h.scope == "team"]
        # every quote the report shows is checked against its own entry (invariants.drop_unverified)
        inputs.record_texts = record_texts(ledger, material.workspace, table)
        report = await build_report(
            inputs, agent_hits, team_hits, findings.awareness,
            None if out_of_budget or rec.data is None else model,
            notes_md, cost=None, extra_gaps=gaps, turning_points=findings.turning_points,
            expected_moment=findings.expected_moment, model_leads=findings.leads, little_happened=note,
            monitor_checks=findings.monitor, evidence=[as_item(i) for i in table.items.values()],
            judge_notes=judge_notes(first_problems, merged_answer, rec, findings, leaves, table),
        )
    actual = _difference(spent_before, _spend(budget))
    read = manifest.spans_by_model()
    report.coverage += "; two-pass judge: " + coverage_note + "".join(
        f"; read by {m}: {', '.join(r[:6])}{' ...' if len(r) > 6 else ''}" for m, r in read.items())
    if projection.fallback_chunks:
        report.coverage += f"; cost plan: {projection.plan}"
    if not_reused:
        report.coverage += f"; {not_reused}"
    if record is not None:
        record(decisions)
    if findings.corrections:
        report.coverage += "; judge corrections: " + "; ".join(findings.corrections)
    cstats = compaction_stats(ledger, view)
    report.stats.update({
        "judge_engine": "two-pass",
        "ledger_entries": len(ledger.events),
        "ledger_entries_read": len(ledger.events) - len(set(manifest.unread())),
        "ledger_unique_chars": cstats["unique_chars"],
        "compacted_chars": cstats["compacted_chars"],
        "chunks": len(chunks),
        "chunks_incomplete": sum(1 for leaf in leaves if not leaf.ok),
        "chunks_fallback": len(projection.fallback_chunks),
        "chunks_resumed": len(resumed),
        "chunk_notes": sum(len(r.notes) for r in reviews),
        "reconcile_tool_calls": len(rec.tool_uses),
        "judge_readers": ", ".join(read) or model_name,
        "evidence_items": len(table.items),
        "cite_calls": sum(len(leaf.cites) for leaf in leaves) + len(table.calls),
        "cite_misses": sum(1 for c in [x for leaf in leaves for x in leaf.cites] + table.calls
                           if c.get("result") in ("miss", "unknown", "refused")),
    })
    if projection.total_usd is not None:
        report.stats["judge_projected_usd"] = round(projection.total_usd, 4)
    if actual["usd"] is not None:
        report.stats["judge_sample_usd"] = round(actual["usd"], 4)
    trace = {
        "sample_id": inputs.sample_id,
        "epoch": inputs.epoch,
        "ledger": digest,
        "cost": {"projected": projection.to_json(), "actual": actual},
        "manifest": manifest.to_json(),
        "chunks": [
            {"id": leaf.chunk.id, "entries": leaf.chunk.span(), "context": leaf.chunk.context, "ok": leaf.ok,
             "error": leaf.error, "model": leaf.model, "dropped_quotes": leaf.dropped_quotes,
             "dropped_notes": getattr(leaf, "dropped_notes", []),
             "triggers": triggers.get(leaf.chunk.id.split(".")[0], []), "resumed": leaf in resumed,
             "rounds": leaf.rounds, "cites": leaf.cites,
             "notes": [n.__dict__ for n in leaf.notes],
             "evidence": {i.id: table.resolved.get((leaf.chunk.id, i.id)) for i in leaf.evidence}}
            for leaf in leaves
        ],
        "evidence": table.to_json(),
        "final_review_cites": table.calls,
        "monitor_checks": [m.model_dump(mode="json") for m in findings.monitor],
        "inferred_links": [
            {"kind": "reply", "message": n.extra.get("message"), "reply": n.extra.get("reply"), "chunk": n.chunk}
            for r in reviews for n in r.notes if n.type == "reply"
        ],
        "required_checks": checks,
        "reconcile": {"error": rec.error, "tool_uses": trace_tool_uses(rec.tool_uses), "answer": rec.data,
                      "prompt_chars": rec.prompt_chars, "tools_stopped_by_budget": rec.tools_stopped_by_budget},
        "problems_sent_back": first_problems,
        "repair_error": rec.repair_error,
        "repair_answer": rec.repaired,
        "answer_after_repair": merged_answer,
        "corrections": findings.corrections,
        "unresolved": findings.unresolved,
        # what a resumed judging can reuse: every part that was read successfully
        "progress": {"key": key, "ledger": digest, "dry_run": dry_run,
                     "reviews": [review_to_json(leaf) for leaf in leaves if leaf.ok]},
        "decisions": decisions,
    }
    return report, findings.hits + findings.awareness, trace
