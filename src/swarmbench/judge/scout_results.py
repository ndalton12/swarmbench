"""Write the judge's scanner results in Inspect Scout's own format.

The judge calls ``llm_scanner`` directly on each agent's turns (that is what
gives it control over attribution). To make those results open in Scout's
viewer (``swarm view --scout`` runs ``scout view --scans <run>/scans -T
<run>/logs``), they are written with Scout's own ``scan()`` machinery, using
*replay* scanners: each one returns the results the judge already computed for
a transcript. No model is called, so the model cost is not doubled, and the
files are exactly what Scout writes for any scan.

Each result links back to its source:

- the transcript is the eval sample itself (Scout's transcript id is the sample uuid);
- an event reference ``[E1]`` points at the agent's span (for turns made
  through another agent's bridge, the bridge owner's span where they landed);
- message references ``[M1]``, ``[M2]``... point at the messages the quotes
  came from (for team scanners, at the ``swarm.message`` events).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspect_scout import Reference, Result
from inspect_scout._transcript.types import Transcript  # module level: Scout reads the type hints

from swarmbench.judge.extract import AgentView, SampleInputs, message_text, render_message
from swarmbench.judge.report import (
    _haystack,
    _hit_label,
    _quotes_from_explanation,
    _scrub_explanation,
    _verify_quotes,
)
from swarmbench.judge.scanners import ScanHit

SCAN_NAME = "swarmbench-judge"
BRIDGE_SCANNER = "bridge_attribution"


def _view_for(hit: ScanHit, inputs: SampleInputs) -> AgentView | None:
    for view in inputs.views():
        if view.name == hit.agent and view.acting_as == hit.acting_as and view.basis == hit.basis:
            return view
    return None


def _quote_source(quote: str, hit: ScanHit, inputs: SampleInputs, view: AgentView | None) -> Reference | None:
    """Where a verified quote came from, as a message or event reference (cite set later)."""
    if hit.scope == "team" or hit.agent is None:
        for m in inputs.messages:
            if quote in render_message(m):
                event_id = inputs.message_event_ids.get(m.get("id"))
                if event_id:
                    return Reference(type="event", id=event_id)
        return None
    for m in (view.messages if view else []):
        if m.id and quote in message_text(m):
            return Reference(type="message", id=m.id)
    return None


def _result(hit: ScanHit, inputs: SampleInputs) -> Result:
    view = _view_for(hit, inputs)
    label = _hit_label(hit)
    references: list[Reference] = []
    head = label
    if view is not None and view.span_event_id:
        references.append(Reference(type="event", cite="[E1]", id=view.span_event_id))
        head = f"{label} [E1]"

    haystack = _haystack(hit, inputs)
    quotes = list(dict.fromkeys(_verify_quotes(hit.quotes, haystack) + _quotes_from_explanation(hit.explanation, haystack)))
    quoted: list[str] = []
    m_n, e_n = 0, len(references)
    for quote in quotes:
        ref = _quote_source(quote, hit, inputs, view)
        if ref is None:
            continue
        if ref.type == "message":
            m_n += 1
            ref.cite = f"[M{m_n}]"
        else:
            e_n += 1
            ref.cite = f"[E{e_n}]"
        references.append(ref)
        short = quote if len(quote) <= 120 else quote[:117] + "..."
        quoted.append(f'{ref.cite} "{short}"')

    if hit.error:
        body = f"not assessed: {hit.error}"
    else:
        body = _scrub_explanation(hit.explanation, haystack) or ("yes" if hit.value else "no")
    explanation = f"{head}: {body}"
    if quoted:
        explanation += "\n\nQuoted: " + "; ".join(quoted)

    if hit.key == "eval_awareness":
        value: Any = None if hit.error else hit.label
        answer = None if hit.error else hit.label
    elif hit.level is not None or (hit.error and hit.key != "eval_awareness_screen"):
        # how-far categories: the value is the level 0-4
        from swarmbench.judge.scanners import LEVEL_NAMES

        value = None if hit.error or hit.level is None else hit.level
        answer = None if value is None else LEVEL_NAMES[value]
    else:
        value = None if hit.error else bool(hit.value)
        answer = None if hit.error else ("Yes" if hit.value else "No")

    return Result(
        value=value,
        answer=answer,
        explanation=explanation,
        label=label,
        references=references,
        metadata={
            "agent": hit.agent,
            "acting_as": hit.acting_as,
            "attribution": hit.basis or None,
            "behavior": hit.behavior,
            "severity": hit.severity,
            "scope": hit.scope,
            "assessed": hit.error is None,
            "level": hit.level,
            "covered_up": hit.covered_up,
            "level_before": hit.before,
            "level_after": hit.after,
        },
    )


def _bridge_result(use: dict[str, str], inputs: SampleInputs) -> Result:
    owner = next((a for a in inputs.agents if a.name == use["owner"]), None)
    references = []
    head = f"{use['actor']} -> {use['owner']}'s bridge"
    if owner is not None and owner.span_event_id:
        references.append(Reference(type="event", cite="[E1]", id=owner.span_event_id))
        head += " [E1]"
    what = "model calls" if use["kind"] == "model_calls" else "a connection only (no model call confirmed)"
    return Result(
        value=use["kind"] == "model_calls",
        answer=use["kind"],
        label=f"{use['actor']} via {use['owner']}",
        explanation=f"{head}: {what}; attributed by {use['basis']}.",
        references=references,
        metadata=dict(use),
    )


def results_for_sample(inputs: SampleInputs, hits: list[ScanHit]) -> dict[str, list[Result]]:
    """Every scanner's results for one sample, keyed by scanner name."""
    out: dict[str, list[Result]] = {}
    for hit in hits:
        out.setdefault(hit.key, []).append(_result(hit, inputs))
    for use in inputs.bridge_uses:
        out.setdefault(BRIDGE_SCANNER, []).append(_bridge_result(use, inputs))
    return out


def _replay_scanner(name: str, records: dict[str, dict[str, list[Result]]]) -> Any:
    from inspect_scout import scanner

    @scanner(name=name, messages="all")
    def replay() -> Any:
        async def run(transcript: Transcript) -> list[Result]:
            return records.get(transcript.transcript_id, {}).get(name, [])

        return run

    return replay()


async def write_scout_results(
    logs_dir: Path,
    scans_dir: Path,
    records: dict[str, dict[str, list[Result]]],
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Write ``records`` ({transcript id: {scanner: results}}) as one Scout scan.

    Returns the scan's location, or None when there was nothing to write.
    """
    from inspect_scout import ScanJob, transcripts_from
    from inspect_scout.aio import scan_async

    names = sorted({name for per_scanner in records.values() for name in per_scanner})
    if not names:
        return None
    job = ScanJob(
        name=SCAN_NAME,
        scanners={name: _replay_scanner(name, records) for name in names},
        transcripts=transcripts_from(str(logs_dir)),
        scans=str(scans_dir),
        max_processes=1,  # the replay data lives in this process
        tags=["swarmbench", "judge"],
        metadata={"note": "judge results replayed into Scout; no model was called", **(metadata or {})},
    )
    status = await scan_async(job)
    return status.location
