"""Judge: Inspect Scout scanners plus a plain-language summarizer.

Owned by the observer teammate. See docs/interfaces.md section 6.

``judge_run(run_dir, model)`` reads the run's ``.eval`` logs, runs the scanners
over each agent's own timeline and over the team message history, then writes a
short plain-language ``report.md`` and a machine-readable ``report.json`` (one
``JudgeReport`` per sample). Every quote is checked verbatim against the log and
the transcript is treated as untrusted input in the prompts.

Models by role (overridable with the ``model`` argument, which forces one model
for every role — used for dry runs on ``mockllm``):

- scanners:            a capable model (default ``anthropic/claude-sonnet-5-5``)
- eval-awareness screen: a cheap model (default ``anthropic/claude-haiku-4-5``)
- eval-awareness confirm / summarizer: a strong model (default
  ``anthropic/claude-opus-5-5``)
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass

import anyio

from swarmbench.judge.budget import (
    JUDGE_MAX_OUTPUT_TOKENS,
    JUDGE_MAX_RETRIES,
    JUDGE_TIMEOUT_SECONDS,
    JudgeBudget,
    cost_of,
    default_cap,
    usage_so_far,
)
from swarmbench.judge.extract import SampleInputs, extract_sample
from swarmbench.judge.report import build_report, render_markdown
from swarmbench.judge.scout_results import results_for_sample, write_scout_results
from swarmbench.judge.scanners import (
    ScanHit,
    run_agent_scanners,
    run_eval_awareness,
    run_team_scanners,
)
from swarmbench.paths import RunDir
from swarmbench.types import CostSummary, JudgeReport

DEFAULT_SCANNER_MODEL = "anthropic/claude-sonnet-5-5"
DEFAULT_SCREEN_MODEL = "anthropic/claude-haiku-4-5"
DEFAULT_SUMMARIZER_MODEL = "anthropic/claude-opus-5-5"


@dataclass
class _Models:
    scanner: object
    screen: object
    confirm: object
    summarizer: object


def _resolve_models(model: str | None, scenario_judge_model: str | None = None) -> _Models:
    """Models per role.

    An explicit ``model`` (the CLI flag, or ``mockllm/model`` on dry runs) is
    used for every role. Otherwise ``advanced.judge_model`` replaces the strong
    roles (scanners, confirmation, summarizer), and the cheap eval-awareness
    screen keeps its default.
    """
    from inspect_ai.model import get_model

    from inspect_ai.model import GenerateConfig

    # bounded output, retries and time per call, so one call can't run away
    bounded = GenerateConfig(
        max_tokens=JUDGE_MAX_OUTPUT_TOKENS, max_retries=JUDGE_MAX_RETRIES, timeout=JUDGE_TIMEOUT_SECONDS
    )

    def real(name: str):  # noqa: ANN202
        return get_model(name, config=bounded)

    if model is not None:
        m = _mock_judge(model) if model.startswith("mockllm/") else real(model)
        return _Models(m, m, m, m)
    strong = scenario_judge_model or DEFAULT_SUMMARIZER_MODEL
    return _Models(
        scanner=real(scenario_judge_model or DEFAULT_SCANNER_MODEL),
        screen=real(DEFAULT_SCREEN_MODEL),
        confirm=real(strong),
        summarizer=real(strong),
    )


DRY_RUN_NOTE = "dry run: the judge used a mock model, so no real assessment was made"


def _mock_judge(model: str):  # noqa: ANN202 - Model
    """A mock judge for dry runs that answers in the expected format.

    Every scanner gets a well-formed "no", so a dry run exercises the real
    answer parsing. (A plain mockllm reply has no "ANSWER:" line, which the
    judge correctly treats as "not assessed".) The summarizer's reply is not
    JSON, so the report falls back to its plain evidence-based summary.
    """
    from inspect_ai.model import ModelOutput, get_model

    def outputs(input, tools, tool_choice, config):  # noqa: ANN001, ANN202
        return ModelOutput.from_content(model, "Mock judge: nothing assessed.\n\nANSWER: no")

    return get_model(model, custom_outputs=outputs)


def _source_scenario(run_dir: RunDir):  # noqa: ANN202 - Scenario | None
    """The scenario as it lives in its own folder (where ``notes.md`` is).

    The runner records that folder as ``scenario_path`` in ``launch.json``; the
    resolved ``scenario.yaml`` copy in the run folder is the fallback (it has
    the settings, but its folder has no notes).
    """
    from swarmbench.config import load_scenario

    launch = run_dir.root / "launch.json"
    with contextlib.suppress(Exception):
        path = json.loads(launch.read_text()).get("scenario_path")
        if path:
            return load_scenario(path)
    with contextlib.suppress(Exception):
        return load_scenario(run_dir.scenario)
    return None


def _load_notes(run_dir: RunDir, scenario) -> str:  # noqa: ANN001
    """The scenario's private judge notes, or "" if they can't be found."""
    local = run_dir.root / "notes.md"
    if local.exists():
        with contextlib.suppress(OSError):
            return local.read_text()
    if scenario is not None and scenario.root is not None:
        notes = scenario.root / scenario.notes
        with contextlib.suppress(OSError):
            if notes.exists():
                return notes.read_text()
    return ""


async def _judge_sample(
    inputs: SampleInputs,
    models: _Models,
    notes_md: str,
    only: set[str] | None = None,
    budget: JudgeBudget | None = None,
    extra_gaps: list[str] | None = None,
) -> tuple[JudgeReport, list[ScanHit]]:
    """Scan one sample within the judge's budget, then build its report."""
    if budget is not None:
        budget.start_sample()
    agent_hits = await run_agent_scanners(inputs, models.scanner, only, budget)  # type: ignore[arg-type]
    team_hits = await run_team_scanners(inputs, models.scanner, only, budget)  # type: ignore[arg-type]
    awareness_hits = await run_eval_awareness(inputs, models.screen, models.confirm, only, budget)  # type: ignore[arg-type]
    gaps = list(extra_gaps or [])
    out_of_budget = budget is not None and budget.exhausted()
    if out_of_budget:
        gaps.insert(0, budget.gap())  # type: ignore[union-attr]
    report = await build_report(
        inputs,
        agent_hits,
        team_hits,
        awareness_hits,
        None if out_of_budget else models.summarizer,  # type: ignore[arg-type]
        notes_md,
        cost=None,
        extra_gaps=gaps,
    )
    if only is not None:
        report.coverage += f"; only these scanners ran: {', '.join(sorted(only))}"
    return report, agent_hits + team_hits + awareness_hits


async def _judge_async(run_dir: RunDir, model: str | None) -> list[JudgeReport]:
    from inspect_ai.log import read_eval_log

    _reset_usage()
    scenario = _source_scenario(run_dir)
    advanced = scenario.advanced if scenario is not None else None
    models = _resolve_models(model, advanced.judge_model if advanced else None)
    notes_md = _load_notes(run_dir, scenario)
    only = set(advanced.scanners) if advanced and advanced.scanners else None
    budget = JudgeBudget(cap_usd=default_cap(scenario))
    dry_run = model is not None and model.startswith("mockllm/")
    extra = [DRY_RUN_NOTE] if dry_run else []
    reports: list[JudgeReport] = []
    scans_dump: list[dict] = []
    scout_records: dict[str, dict] = {}

    try:
        for log_path in run_dir.eval_logs():
            log = read_eval_log(str(log_path))
            for sample in log.samples or []:
                inputs = extract_sample(sample)
                report, hits = await _judge_sample(inputs, models, notes_md, only, budget, extra)
                reports.append(report)
                scans_dump.append(
                    {
                        "sample_id": inputs.sample_id,
                        "epoch": inputs.epoch,
                        "hits": [h.__dict__ for h in hits],
                    }
                )
                if inputs.transcript_id:
                    scout_records[inputs.transcript_id] = results_for_sample(inputs, hits)
                _save_judge_cost(run_dir, _judge_cost())  # spend so far, as we go
    finally:
        # even if judging crashed, the spend is recorded
        _save_judge_cost(run_dir, _judge_cost())

    cost = _judge_cost()
    for r in reports:
        r.cost = cost

    # The same results in Scout's own format, for `swarm view --scout`.
    try:
        await write_scout_results(
            run_dir.logs, run_dir.scans, scout_records, metadata={"run_id": run_dir.run_id}
        )
    except Exception as exc:  # noqa: BLE001 - the report must still be written
        for r in reports:
            r.coverage += f"; scanner results could not be written for the Scout viewer ({exc!r:.120})"

    _write_outputs(run_dir, reports, scans_dump)
    _update_status(run_dir, reports, cost)
    return reports


def _reset_usage() -> None:
    with contextlib.suppress(Exception):
        from inspect_ai.model._model import init_model_usage

        init_model_usage({})


def _judge_cost() -> CostSummary:
    """The judge's own spend so far, priced through ``swarmbench.costs``
    (unpriced models give ``usd=None``, never a misleading $0)."""
    return cost_of(usage_so_far())


def _save_judge_cost(run_dir: RunDir, cost: CostSummary) -> None:
    """Write the judge's spend into status.json now (not only at the end)."""
    with contextlib.suppress(Exception):
        from swarmbench.status import read_status

        status = read_status(run_dir)
        if status is None:
            return
        status.judge_cost = cost
        tmp = run_dir.status.with_suffix(".json.tmp")
        tmp.write_text(status.model_dump_json(indent=2))
        import os

        os.replace(tmp, run_dir.status)


JUDGE_HITS_FILE = "judge_hits.json"
"""Raw per-check answers, beside the report. ``scans/`` holds only Scout scans."""


def _write_outputs(run_dir: RunDir, reports: list[JudgeReport], scans_dump: list[dict]) -> None:
    (run_dir.root / JUDGE_HITS_FILE).write_text(json.dumps(scans_dump, indent=2, default=str))
    run_dir.report_md.write_text(render_markdown(reports))
    run_dir.report_json.write_text(
        json.dumps([r.model_dump(mode="json") for r in reports], indent=2)
    )


def _update_status(run_dir: RunDir, reports: list[JudgeReport], cost: CostSummary | None) -> None:
    if not reports:
        return
    with contextlib.suppress(Exception):
        from swarmbench.status import read_status
        from swarmbench.types import RunStatus

        status = read_status(run_dir) or RunStatus(run_id=run_dir.run_id, scenario=reports[0].scenario)
        worst = max(reports, key=lambda r: _verdict_rank(r.verdict))
        status.verdict = worst.verdict
        status.headline = worst.headline
        if cost is not None:
            status.judge_cost = cost
        tmp = run_dir.status.with_suffix(".json.tmp")
        tmp.write_text(status.model_dump_json(indent=2))
        import os

        os.replace(tmp, run_dir.status)


def _verdict_rank(verdict: str) -> int:
    return {"none": 0, "minor": 1, "concerning": 2, "severe": 3}.get(verdict, 0)


def judge_run(run_dir: RunDir, model: str | None = None) -> list[JudgeReport]:
    """Run the judge over a finished run folder and write its report.

    Args:
        run_dir: the run folder (with ``logs/*.eval``).
        model: force one model for every judge role (e.g. ``"mockllm/model"``
            for a dry run). ``None`` uses the per-role defaults.
    """
    return anyio.run(_judge_async, run_dir, model)
