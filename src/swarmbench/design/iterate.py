"""Revising a scenario using the evidence from its runs."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from inspect_ai.model import Model

from swarmbench.design.checks import validate
from swarmbench.design.context import realism_checklist
from swarmbench.design.drafting import DesignError, draft_until_valid, show_files
from swarmbench.design.evidence import RunEvidence, collect, render
from swarmbench.design.folder import next_version, publish, read_folder, write_files
from swarmbench.design.llm import Chat, Usage, resolve_model
from swarmbench.design.new import Echo
from swarmbench.design.prompts import designer_system, iterate_request
from swarmbench.design.signals import Finding, diagnose
from swarmbench.paths import RunDir

CHANGES_FILE = "CHANGES.md"


async def iterate_scenario_async(
    scenario_dir: Path,
    run_dirs: list[RunDir],
    out_dir: Path | None = None,
    model: str | Model | None = None,
    *,
    checklist: Path | None = None,
    echo: Echo | None = print,
) -> Path:
    """Write a revised copy of ``scenario_dir`` informed by ``run_dirs``. See ``swarmbench.design``."""
    out_dir = Path(out_dir) if out_dir is not None else None
    scenario_dir = Path(scenario_dir)
    if not (scenario_dir / "scenario.yaml").is_file():
        raise FileNotFoundError(f"no scenario.yaml in {scenario_dir}")
    if out_dir is not None:
        if out_dir.exists() or out_dir.is_symlink():
            raise FileExistsError(f"{out_dir} already exists; the designer never overwrites")
        target, version = out_dir, None
    else:
        target, version = next_version(scenario_dir)
    if not run_dirs:
        raise ValueError("give at least one run folder to learn from")

    evidence = [collect(r) for r in run_dirs]
    if all(ev.empty for ev in evidence):
        problems = [f"{ev.run_id}: {'; '.join(ev.problems) or 'nothing found'}" for ev in evidence]
        raise DesignError("none of the runs has a judge report, monitor flags or scanner results", problems)

    texts, binaries = read_folder(scenario_dir)
    original_texts, original_binaries = dict(texts), dict(binaries)
    old_changes = texts.pop(CHANGES_FILE, None)
    current = validate(texts, binaries)
    shown, readonly = show_files(texts)
    if current.errors:
        shown += "\n\nThe current scenario does not load. Fix these too:\n" + "\n".join(
            f"- {e}" for e in current.errors
        )
    if old_changes:
        shown += f"\n\nThe previous version's CHANGES.md, for context:\n<previous_changes>\n{old_changes}\n</previous_changes>"

    llm = resolve_model(model)
    usage = Usage()
    checklist_text, _ = realism_checklist(checklist)
    chat = Chat(llm, designer_system(checklist_text, ""), usage)
    findings = signals_from(evidence)
    request = iterate_request(
        shown,
        "\n\n".join(render(ev) for ev in evidence),
        [ev.run_id for ev in evidence],
        "\n".join(f"- {f.title} {f.advice}" for f in findings),
    )

    def needs_changes_file(files: dict[str, str]) -> list[str]:
        if not files.get(CHANGES_FILE, "").strip():
            return [f"{CHANGES_FILE} is missing: explain each change and the run evidence behind it"]
        return []

    draft = await draft_until_valid(
        chat, request, files=texts, binaries=binaries, readonly=readonly, extra_check=needs_changes_file
    )
    files = draft.files
    if version is not None:
        renamed = _rename(files["scenario.yaml"], version)
        if renamed and validate({**files, "scenario.yaml": renamed}, draft.binaries).ok:
            files["scenario.yaml"] = renamed

    changed = _diff(original_texts, original_binaries, files, draft.binaries)
    files[CHANGES_FILE] = _with_appendix(files[CHANGES_FILE], scenario_dir, changed, evidence, findings)
    with tempfile.TemporaryDirectory(prefix="swarm-design-") as tmp:
        staging = Path(tmp) / "scenario"
        write_files(staging, files, draft.binaries)
        publish(staging, target)

    if echo:
        echo(
            _summary(
                scenario_dir, target, files[CHANGES_FILE], changed, draft.check.warnings, usage, llm, findings
            )
        )
    return target


def signals_from(evidence: list[RunEvidence]) -> list[Finding]:
    """Findings from the screening signals across all the runs."""
    awareness = [r.eval_awareness for ev in evidence for r in ev.reports]
    time_limits = [ev.time_limit_s for ev in evidence if ev.time_limit_s]
    return diagnose(
        moments=[m for ev in evidence for m in ev.moments],
        levels=[lv for ev in evidence for lv in ev.levels],
        awareness=awareness,
        screens=[ev.screen for ev in evidence if ev.screen],
        time_limit_s=min(time_limits) if time_limits else None,
        turning_points=[tp for ev in evidence for tp in ev.turning_points],
        leads=[lead for ev in evidence for lead in ev.leads],
        short_agents=[a for ev in evidence for a in ev.short_agents],
        quiet=[q for ev in evidence for q in ev.quiet],
    )


def _rename(yaml_text: str, version: int) -> str | None:
    """Give the new version its own scenario name, e.g. impossible-math-v2."""
    match = re.search(r"^name:[ \t]*['\"]?([A-Za-z0-9_.-]+)['\"]?[ \t]*$", yaml_text, re.MULTILINE)
    if not match:
        return None
    base = re.sub(r"-v\d+$", "", match.group(1))
    return yaml_text[: match.start()] + f"name: {base}-v{version}" + yaml_text[match.end() :]


def _diff(
    old_texts: dict[str, str], old_bins: dict[str, bytes], texts: dict[str, str], bins: dict[str, bytes]
) -> dict[str, list[str]]:
    old = {**old_texts, **old_bins}
    new = {**texts, **bins}
    skip = {CHANGES_FILE}
    return {
        "added": sorted(p for p in new if p not in old and p not in skip),
        "changed": sorted(p for p in new if p in old and new[p] != old[p] and p not in skip),
        "removed": sorted(p for p in old if p not in new and p not in skip),
    }


def _with_appendix(
    text: str, source: Path, changed: dict[str, list[str]], evidence: list, findings: list[Finding]
) -> str:
    lines = [text.rstrip(), ""]
    if findings:
        lines += ["## Signals from the runs (recorded automatically)", ""]
        lines += [f"- {f.title}" for f in findings]
        lines.append("")
    lines += ["## Files changed (recorded automatically)", ""]
    lines.append(f"Revised from `{source}`.")
    for kind in ("added", "changed", "removed"):
        if changed[kind]:
            lines.append(f"- {kind.capitalize()}: " + ", ".join(f"`{p}`" for p in changed[kind]))
    if not any(changed.values()):
        lines.append("- No files changed.")
    lines.append("")
    lines.append("Runs used as evidence: " + ", ".join(f"`{ev.run_id}`" for ev in evidence))
    return "\n".join(lines) + "\n"


def _summary(
    source: Path,
    target: Path,
    changes: str,
    changed: dict[str, list[str]],
    warnings: list[str],
    usage: Usage,
    llm: Model,
    findings: list[Finding] | None = None,
) -> str:
    headings = [h.strip("# ").strip() for h in changes.splitlines() if h.startswith("## ")]
    headings = [
        h
        for h in headings
        if not h.startswith(("Files changed", "Signals from the runs"))
        and h != "What to look for in the next runs"
    ]
    lines = [f"Wrote a revised version of {source} to {target}."]
    if findings:
        lines.append("What the runs showed:")
        lines += [f"  - {f.title}" for f in findings]
    if headings:
        lines.append("Changes (details and the evidence for each are in CHANGES.md):")
        lines += [f"  - {h}" for h in headings]
    counts = ", ".join(f"{len(v)} {k}" for k, v in changed.items() if v) or "no files changed"
    lines.append(f"Files: {counts}.")
    if warnings:
        lines.append("Possible giveaways flagged by the word check (check these by hand):")
        lines += [f"  - {w}" for w in warnings[:10]]
    lines.append(f"Model use: {usage.line(str(llm))}.")
    lines.append(
        f"Next: `swarm check {target}`, then `swarm run {target}` and compare with the earlier runs."
    )
    return "\n".join(lines)
