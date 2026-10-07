"""Drafting a new scenario: from an idea, or from a striking moment in a past run."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import yaml
from inspect_ai.model import Model

from swarmbench.design.blocks import format_files, section
from swarmbench.design.checks import visible_files
from swarmbench.design.context import examples, find_scenarios_dir, realism_checklist
from swarmbench.design.drafting import DesignError, Draft, draft_until_valid
from swarmbench.design.evidence import collect, find_moment, transcript_lines
from swarmbench.design.folder import free_name, publish, slugify, write_files
from swarmbench.design.history import HISTORY_FILE
from swarmbench.design.llm import Chat, Usage, resolve_model
from swarmbench.design.prompts import (
    critique_request,
    critique_system,
    designer_system,
    moment_idea,
    new_request,
)
from swarmbench.paths import RunDir

Echo = Callable[[str], None]


async def new_scenario_async(
    idea: str,
    out_dir: Path | None = None,
    model: str | Model | None = None,
    *,
    scenarios_dir: Path | None = None,
    checklist: Path | None = None,
    critique: bool = True,
    echo: Echo | None = print,
    origin: str | None = None,
) -> Path:
    """Draft a scenario folder from ``idea`` and return its path. See ``swarmbench.design``."""
    out_dir = Path(out_dir) if out_dir is not None else None
    if out_dir is not None and (out_dir.exists() or out_dir.is_symlink()):
        raise FileExistsError(f"{out_dir} already exists; the designer never overwrites")
    llm = resolve_model(model)
    usage = Usage()
    checklist_text, checklist_source = realism_checklist(checklist)
    found_dir = find_scenarios_dir(scenarios_dir)
    system = designer_system(checklist_text, examples(found_dir))

    draft = await draft_until_valid(Chat(llm, system, usage), new_request(idea))
    final, critique_text, critique_note = draft, None, None
    if critique:
        final, critique_text, critique_note = await _realism_pass(llm, usage, checklist_text, draft)

    scenario = final.check.scenario
    assert scenario is not None
    target = out_dir or free_name(scenarios_dir or found_dir or Path("scenarios"), slugify(scenario.name))
    log = _design_log(
        idea=idea,
        origin=origin,
        model=llm,
        usage=usage,
        checklist_source=checklist_source,
        draft=draft,
        final=final,
        critique_text=critique_text,
        critique_note=critique_note,
    )
    files = {**final.files, "design_log.md": log}
    with tempfile.TemporaryDirectory(prefix="swarm-design-") as tmp:
        staging = Path(tmp) / "scenario"
        write_files(staging, files, final.binaries)
        publish(staging, target)

    if echo:
        echo(_summary(target, final, usage, llm, critique_text, critique_note, draft))
    return target


async def scenario_from_moment_async(
    run_dir: RunDir,
    moment: str,
    out_dir: Path | None = None,
    model: str | Model | None = None,
    *,
    scenario_dir: Path | None = None,
    scenarios_dir: Path | None = None,
    checklist: Path | None = None,
    echo: Echo | None = print,
) -> Path:
    """Draft a new scenario that recreates a moment from a past run.

    ``moment`` is a quote or short description. Transcript lines and judge
    concerns that contain it are given to the model; if nothing matches, the
    moment text alone is used and the summary says so.
    """
    try:
        excerpts = find_moment(transcript_lines(run_dir), moment)
    except Exception:
        excerpts = []
    needle = moment.lower()
    concerns = []
    for report in collect(run_dir).reports:
        for c in report.concerns:
            haystack = " ".join([c.behavior, c.explanation, *c.quotes]).lower()
            if needle in haystack:
                quotes = "; ".join(f'"{q}"' for q in c.quotes[:3])
                concerns.append(
                    f"{c.behavior} ({c.severity}, {', '.join(c.agents)}): {c.explanation} {quotes}"
                )
    notes = ""
    if scenario_dir and (scenario_dir / "notes.md").is_file():
        notes = (scenario_dir / "notes.md").read_text()
    idea = moment_idea(moment, notes, excerpts, concerns)
    origin = f"run {run_dir.run_id}, moment: {moment!r}"
    if not excerpts and not concerns:
        origin += " (not found in the run's transcripts or report; drafted from the description alone)"
    return await new_scenario_async(
        idea, out_dir, model, scenarios_dir=scenarios_dir, checklist=checklist, echo=echo, origin=origin
    )


async def _realism_pass(
    llm: Model, usage: Usage, checklist_text: str, draft: Draft
) -> tuple[Draft, str | None, str | None]:
    """A second model critiques the visible files against the checklist and revises them."""
    visible = visible_files(draft.files, draft.check.scenario)
    hidden = {p: t for p, t in draft.files.items() if p not in visible}
    request = critique_request(format_files(visible), format_files(hidden), draft.check.warnings)
    chat = Chat(llm, critique_system(checklist_text), usage)
    try:
        revised = await draft_until_valid(chat, request, files=draft.files, binaries=draft.binaries)
    except DesignError as e:
        note = "The realism revision did not load, so the first draft was kept. Problems: " + "; ".join(
            e.errors[:3]
        )
        return draft, None, note
    text = section(revised.replies[0], "critique") or "(the reviewer wrote no critique)"
    return revised, text, None


def _summary(
    target: Path,
    final: Draft,
    usage: Usage,
    llm: Model,
    critique_text: str | None,
    critique_note: str | None,
    draft: Draft,
) -> str:
    s = final.check.scenario
    assert s is not None
    teams = s.resolved_teams()
    workspace_files = [
        p for p in final.files if any(p.startswith(f"{t.workspace}/") for t in teams if t.workspace)
    ]
    commits = _commit_count(final.files)
    lines = [f"Created a new scenario '{s.name}' in {target}."]
    if s.description:
        lines.append(f"What it is: {s.description}")
    for t in teams:
        label = f"Team {t.name}: " if s.multi_team else ""
        lines.append(f"{label}{t.agents} agents on {t.model} ({t.harness}), messaging: {t.messaging}.")
    lines.append(
        f"Files: {len(final.files) + len(final.binaries)} in total, {len(workspace_files)} in the workspace; "
        + (f"git history of {commits} commits." if commits else "no git history.")
    )
    if draft.repairs:
        lines.append(f"The first draft needed {len(draft.repairs)} repair round(s) before it loaded.")
    if critique_note:
        lines.append(critique_note)
    elif critique_text:
        lines.append("A realism review then revised it. The reviewer's points:")
        lines.append(_indent(_trim(critique_text, 1500)))
    if final.check.warnings:
        lines.append("Possible giveaways still flagged by the word check (check these by hand):")
        lines += [f"  - {w}" for w in final.check.warnings[:10]]
    lines.append(f"Model use: {usage.line(str(llm))}.")
    lines.append(f"Full design notes: {target / 'design_log.md'}.")
    lines.append(f"Next: read notes.md, then `swarm check {target}` and `swarm run {target} --dry-run`.")
    return "\n".join(lines)


def _design_log(
    *,
    idea: str,
    origin: str | None,
    model: Model,
    usage: Usage,
    checklist_source: str,
    draft: Draft,
    final: Draft,
    critique_text: str | None,
    critique_note: str | None,
) -> str:
    parts = [
        "# Design log",
        "",
        "Written by `swarm design`. Agents never see this file.",
        "",
        f"- Created: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Model: {model} ({usage.line(str(model))})",
        f"- Realism checklist: {checklist_source}",
    ]
    if origin:
        parts.append(f"- Source: {origin}")
    parts += ["", "## Idea", "", idea.strip(), ""]
    if draft.repairs:
        parts += ["## Repairs to the first draft", ""]
        for i, errors in enumerate(draft.repairs, 1):
            parts.append(f"Round {i}:")
            parts += [f"- {e}" for e in errors]
        parts.append("")
    parts += ["## Realism review", ""]
    if critique_note:
        parts.append(critique_note)
    elif critique_text:
        parts.append(critique_text)
        if final.repairs:
            parts.append(f"\nThe revision needed {len(final.repairs)} repair round(s).")
    else:
        parts.append("Skipped.")
    parts += ["", "## Word-check warnings", ""]
    parts += [f"- {w}" for w in final.check.warnings] or ["None."]
    return "\n".join(parts) + "\n"


def _commit_count(files: dict[str, str]) -> int:
    try:
        data = yaml.safe_load(files.get(HISTORY_FILE, "")) or {}
        return len(data.get("commits") or [])
    except yaml.YAMLError:
        return 0


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n[...]"


def _indent(text: str) -> str:
    return "\n".join("  " + line for line in text.splitlines())
