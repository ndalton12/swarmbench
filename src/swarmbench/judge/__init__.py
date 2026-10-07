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

from swarmbench.judge.extract import SampleInputs, extract_sample
from swarmbench.judge.report import build_report, render_markdown
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

    if model is not None:
        m = get_model(model)
        return _Models(m, m, m, m)
    strong = scenario_judge_model or DEFAULT_SUMMARIZER_MODEL
    return _Models(
        scanner=get_model(scenario_judge_model or DEFAULT_SCANNER_MODEL),
        screen=get_model(DEFAULT_SCREEN_MODEL),
        confirm=get_model(strong),
        summarizer=get_model(strong),
    )


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
    inputs: SampleInputs, models: _Models, notes_md: str, only: set[str] | None = None
) -> tuple[JudgeReport, list[ScanHit]]:
    agent_hits = await run_agent_scanners(inputs, models.scanner, only)  # type: ignore[arg-type]
    team_hits = await run_team_scanners(inputs, models.scanner, only)  # type: ignore[arg-type]
    awareness_hits = await run_eval_awareness(inputs, models.screen, models.confirm, only)  # type: ignore[arg-type]
    report = await build_report(
        inputs, agent_hits, team_hits, awareness_hits, models.summarizer, notes_md, cost=None  # type: ignore[arg-type]
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
    reports: list[JudgeReport] = []
    scans_dump: list[dict] = []

    for log_path in run_dir.eval_logs():
        log = read_eval_log(str(log_path))
        for sample in log.samples or []:
            inputs = extract_sample(sample)
            report, hits = await _judge_sample(inputs, models, notes_md, only)
            reports.append(report)
            scans_dump.append(
                {
                    "sample_id": inputs.sample_id,
                    "epoch": inputs.epoch,
                    "hits": [h.__dict__ for h in hits],
                }
            )

    # The judge's own cost, kept separate from the swarm's.
    cost = _judge_cost()
    for r in reports:
        r.cost = cost

    _write_outputs(run_dir, reports, scans_dump)
    _update_status(run_dir, reports, cost)
    return reports


def _reset_usage() -> None:
    with contextlib.suppress(Exception):
        from inspect_ai.model._model import init_model_usage

        init_model_usage({})


def _judge_cost() -> CostSummary | None:
    """Judge token usage priced through ``swarmbench.costs`` when available.

    Degrades gracefully: without the costs module (it lives on the runner's
    branch) the tokens are still reported with ``usd=None`` and every model
    listed as unpriced, so the cost is never shown as a misleading $0.
    """
    usage: dict = {}
    with contextlib.suppress(Exception):
        from inspect_ai.model._model import model_usage_context_var

        usage = dict(model_usage_context_var.get())
    if not usage:
        return CostSummary(tokens=0, usd=None)

    with contextlib.suppress(Exception):
        from swarmbench.costs import usage_cost  # type: ignore[import-not-found]

        return usage_cost(usage)

    # Fallback summary from raw token counts.
    total = sum(getattr(u, "total_tokens", 0) for u in usage.values())
    inp = sum(getattr(u, "input_tokens", 0) for u in usage.values())
    out = sum(getattr(u, "output_tokens", 0) for u in usage.values())
    return CostSummary(
        tokens=total,
        input_tokens=inp,
        output_tokens=out,
        usd=None,
        by_model={name: None for name in usage},
        unpriced_models=sorted(usage),
    )


def _write_outputs(run_dir: RunDir, reports: list[JudgeReport], scans_dump: list[dict]) -> None:
    run_dir.scans.mkdir(parents=True, exist_ok=True)
    (run_dir.scans / "results.json").write_text(json.dumps(scans_dump, indent=2, default=str))
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
