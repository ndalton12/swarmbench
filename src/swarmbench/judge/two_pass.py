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
from swarmbench.judge.compaction import stats as compaction_stats
from swarmbench.judge.extract import SampleInputs
from swarmbench.judge.findings import build_findings, merge_repair
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
from swarmbench.judge.review import behavior_catalogue, review_all, review_system_prompt
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


def ledger_digest(ledger: Ledger) -> str:
    """Identifies a ledger, so saved progress is only reused for the same record."""
    import hashlib

    raw = "\n".join(f"{e.id}:{e.kind}:{e.content}" for e in ledger.events)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


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
) -> tuple[JudgeReport, list[ScanHit], dict[str, Any]]:
    """Judge one sample.

    ``fallback``: a callable returning the fallback reader (a model), resolved only if the plan
    needs it. ``progress``: saved progress from an earlier, interrupted judging of this sample
    (chunk reviews that succeeded are reused when the record is the same)."""
    from swarmbench.judge.reconcile import tool_infos
    from swarmbench.judge.report import build_report
    from swarmbench.judge.review import review_from_json, review_to_json
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
    essential = [c for c in projection.calls if not c.what.startswith(("review", "reconcile: tool"))]
    tool_round = max((c for c in projection.calls if c.what.startswith("reconcile: tool")),
                     key=lambda c: c.input_tokens, default=None)
    if budget is not None:
        budget.set_hold(projection.held_usd, sum(c.input_tokens + c.output_tokens for c in essential))
    assign: dict[str, tuple[Any, str]] = {}
    if projection.fallback_chunks and fallback is not None:
        reader = fallback()
        assign = {cid: (reader, fallback_name) for cid in projection.fallback_chunks}

    # pass 1: every chunk, one open-ended review each (or reused from an interrupted judging)
    earlier = []
    if progress and progress.get("ledger") == digest:
        earlier = [review_from_json(r) for r in progress.get("reviews") or []]
    reviews = await review_all(
        chunks, ledger=ledger, view=view, system=review_system, model=model, model_name=model_name,
        agents=set(agents), manifest=manifest, limiter=limiter, assign=assign, reuse=earlier,
    )
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
    user = reconcile_user_prompt(files, reviews, checks, material.workspace, coverage_note)
    tools = Tools(ledger, view, material.workspace, run_root)

    def can_investigate() -> bool:
        if budget is None or tool_round is None:
            return True
        usd, tokens_left = budget.room()
        if usd is not None and tool_round.usd is not None:
            return usd - tool_round.usd >= budget.hold_usd
        return tokens_left - tool_round.input_tokens - tool_round.output_tokens >= budget.hold_tokens

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
                                  checks=checks)

        findings = validated(rec.data)
        first_problems = list(findings.problems)
        merged_answer = None
        if rec.data is not None and first_problems:
            # findings that failed the record checks go back to the model once; only those are replaced
            fixed = await repair(rec, first_problems, model=model, model_name=model_name, manifest=manifest,
                                 limiter=limiter)
            if fixed is not None:
                merged_answer = merge_repair(rec.data, fixed, findings.problem_keys)
                findings = validated(merged_answer)

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
        if unread:
            gaps.append(f"{RESUME_HINT} to read the {len(unread)} unread entries")
        explicit = sum(1 for h in findings.awareness if h.label == "explicit" and not h.error)
        note = little_happened(findings.turning_points, findings.expected_moment, inputs, explicit) if rec.data else ""
        agent_hits = [h for h in findings.hits if h.scope == "agent"]
        team_hits = [h for h in findings.hits if h.scope == "team"]
        report = await build_report(
            inputs, agent_hits, team_hits, findings.awareness,
            None if out_of_budget or rec.data is None else model,
            notes_md, cost=None, extra_gaps=gaps, turning_points=findings.turning_points,
            expected_moment=findings.expected_moment, model_leads=findings.leads, little_happened=note,
        )
    actual = _difference(spent_before, _spend(budget))
    read = manifest.spans_by_model()
    report.coverage += "; two-pass judge: " + coverage_note + "".join(
        f"; read by {m}: {', '.join(r[:6])}{' ...' if len(r) > 6 else ''}" for m, r in read.items())
    if projection.fallback_chunks:
        report.coverage += f"; cost plan: {projection.plan}"
    if rec.tools_stopped_by_budget:
        report.coverage += "; the final review's checking was cut short to stay within the judge's budget"
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
             "triggers": triggers.get(leaf.chunk.id.split(".")[0], []), "resumed": leaf in resumed,
             "notes": [n.__dict__ for n in leaf.notes]}
            for leaf in leaves
        ],
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
        "progress": {"ledger": digest, "reviews": [review_to_json(leaf) for leaf in leaves if leaf.ok]},
    }
    return report, findings.hits + findings.awareness, trace
