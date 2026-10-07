"""What happened in past runs, condensed for the designer model.

Reads each run folder's judge report (``report.json``), live monitor flags
(``monitor.jsonl``), Scout scanner summaries (``scans/**/_summary.json``) and,
when asked, transcript excerpts from the Inspect logs. Every reader tolerates
missing or malformed files and says what it could not read, so a gap is
never presented as a clean run.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter, ValidationError

from swarmbench.paths import RunDir
from swarmbench.types import JudgeReport, MonitorFlag

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class RunEvidence:
    run_id: str
    settings: str = ""
    reports: list[JudgeReport] = field(default_factory=list)
    flags: list[MonitorFlag] = field(default_factory=list)
    scanners: dict[str, dict[str, int]] = field(default_factory=dict)
    scanner_hits: dict[str, list[str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    """Things that could not be read."""

    @property
    def empty(self) -> bool:
        return not (self.reports or self.flags or self.scanners)


def collect(run_dir: RunDir) -> RunEvidence:
    ev = RunEvidence(run_id=run_dir.run_id)
    if not run_dir.root.is_dir():
        ev.problems.append(f"run folder {run_dir.root} does not exist")
        return ev
    ev.settings = _settings(run_dir)
    _read_reports(run_dir, ev)
    _read_monitor(run_dir, ev)
    _read_scans(run_dir, ev)
    return ev


def _settings(run_dir: RunDir) -> str:
    if not run_dir.scenario.exists():
        return ""
    try:
        data = yaml.safe_load(run_dir.scenario.read_text()) or {}
    except yaml.YAMLError:
        return ""
    swarm = data.get("swarm", {}) or {}
    keys = ["agents", "model", "effort", "harness", "messaging", "token_budget"]
    parts = [f"{k}={swarm[k]}" for k in keys if swarm.get(k) is not None]
    if data.get("teams"):
        parts.append("teams=" + ",".join(str(t.get("name")) for t in data["teams"]))
    return ", ".join(parts)


def _read_reports(run_dir: RunDir, ev: RunEvidence) -> None:
    path = run_dir.report_json
    if not path.exists():
        ev.problems.append("no report.json (the judge has not run, or failed)")
        return
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            data = [data]
        ev.reports = TypeAdapter(list[JudgeReport]).validate_python(data)
    except (json.JSONDecodeError, ValidationError) as e:
        ev.problems.append(f"report.json could not be read: {str(e)[:300]}")


def _read_monitor(run_dir: RunDir, ev: RunEvidence) -> None:
    path = run_dir.monitor
    if not path.exists():
        return
    bad = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            ev.flags.append(MonitorFlag.model_validate_json(line))
        except ValidationError:
            bad += 1
    if bad:
        ev.problems.append(f"{bad} unreadable lines in monitor.jsonl")


def _read_scans(run_dir: RunDir, ev: RunEvidence) -> None:
    if not run_dir.scans.is_dir():
        return
    for summary_file in sorted(run_dir.scans.rglob("_summary.json")):
        try:
            data = json.loads(summary_file.read_text())
        except json.JSONDecodeError:
            ev.problems.append(f"unreadable scanner summary {summary_file.relative_to(run_dir.root)}")
            continue
        for name, s in (data.get("scanners") or {}).items():
            total = ev.scanners.setdefault(name, {"scans": 0, "results": 0, "errors": 0})
            for key in total:
                total[key] += int(s.get(key, 0) or 0)
        ev.scanner_hits.update(_scanner_explanations(summary_file.parent))


def _scanner_explanations(scan_dir: Path, per_scanner: int = 4) -> dict[str, list[str]]:
    """Short explanations of positive scanner results (best effort: needs pandas)."""
    try:
        from inspect_scout import scan_results_df

        results = scan_results_df(str(scan_dir))
        out: dict[str, list[str]] = {}
        for name in results.summary.scanners:
            df = results.scanners[name]
            if "value" not in df.columns:
                continue
            hits = df[df["value"].map(_truthy)]
            col = "explanation" if "explanation" in df.columns else None
            if col is None:
                continue
            texts = [str(x)[:400] for x in hits[col].dropna().tolist()[:per_scanner]]
            if texts:
                out[name] = texts
        return out
    except Exception:  # noqa: BLE001 - the counts above are still useful without these
        return {}


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "none", "null", "no", "[]")
    return bool(value)


def render(ev: RunEvidence, max_flags: int = 15) -> str:
    """One run's evidence as plain text for a prompt."""
    lines = [f'<run id="{ev.run_id}">']
    if ev.settings:
        lines.append(f"Settings: {ev.settings}")
    for r in ev.reports:
        lines.append(f"\n## Judge report (epoch {r.epoch}): verdict {r.verdict}")
        lines.append(f"Headline: {r.headline}")
        lines.append(f"Summary: {r.summary}")
        if r.outcome:
            lines.append(f"Outcome: {r.outcome}")
        if r.coverage:
            lines.append(f"Coverage: {r.coverage}")
        for c in r.concerns:
            lines.append(
                f"- Concern ({c.severity}, agents {', '.join(c.agents)}): {c.behavior}. {c.explanation}"
            )
            lines += [f'    quote: "{q}"' for q in c.quotes[:4]]
        lines.append(f"Eval awareness: {r.eval_awareness or '(none reported)'}")
        if r.realism_notes:
            lines.append("Realism notes:")
            lines += [f"- {n}" for n in r.realism_notes]
        if r.stats:
            lines.append("Stats: " + ", ".join(f"{k}={v}" for k, v in r.stats.items()))
    if ev.flags:
        counts = Counter(f"{f.category}/{f.severity}" for f in ev.flags)
        lines.append("\n## Live monitor flags: " + ", ".join(f"{k} x{n}" for k, n in sorted(counts.items())))
        worst = sorted(ev.flags, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.time))[:max_flags]
        for f in worst:
            who = f.agent or "unknown agent"
            if f.acting_as:
                who += f" (acting as {f.acting_as})"
            lines.append(f"- {f.severity} {f.category}, {who}: {f.summary} [{f.evidence[:200]}]")
    if ev.scanners:
        lines.append("\n## Scanner results (positive / scanned, errors)")
        for name, s in sorted(ev.scanners.items()):
            lines.append(f"- {name}: {s['results']}/{s['scans']}, {s['errors']} errors")
            lines += [f"    hit: {t}" for t in ev.scanner_hits.get(name, [])]
    if ev.problems:
        lines.append("\n## Missing or unreadable evidence")
        lines += [f"- {p}" for p in ev.problems]
    lines.append("</run>")
    return "\n".join(lines)


# --- transcript excerpts ---------------------------------------------------------


@dataclass
class Line:
    agent: str
    kind: str
    text: str


def transcript_lines(run_dir: RunDir) -> list[Line]:
    """A flat, readable list of what each agent said and did, from the run's Inspect logs."""
    from inspect_ai.log import read_eval_log

    out: list[Line] = []
    for log_path in run_dir.eval_logs():
        log = read_eval_log(str(log_path))
        for sample in log.samples or []:
            out += _sample_lines(sample.events)
    return out


def _sample_lines(events: list[Any]) -> list[Line]:
    span_agent: dict[str, str] = {}
    span_parent: dict[str, str | None] = {}
    for e in events:
        if e.event == "span_begin":
            span_parent[e.id] = e.parent_id
            if e.type == "agent":
                span_agent[e.id] = e.name

    def agent_of(span_id: str | None) -> str:
        seen = set()
        while span_id and span_id not in seen:
            seen.add(span_id)
            if span_id in span_agent:
                return span_agent[span_id]
            span_id = span_parent.get(span_id)
        return "?"

    lines: list[Line] = []
    for e in events:
        agent = agent_of(e.span_id)
        if e.event == "model" and e.output and e.output.choices:
            msg = e.output.choices[0].message
            if msg.text:
                lines.append(Line(agent, "says", msg.text))
            for call in msg.tool_calls or []:
                lines.append(Line(agent, f"calls {call.function}", json.dumps(call.arguments)[:2000]))
        elif e.event == "tool":
            result = e.result if isinstance(e.result, str) else str(e.result)
            lines.append(Line(agent, f"result of {e.function}", result[:2000]))
        elif e.event == "info" and e.source == "swarm.message" and isinstance(e.data, dict):
            sender = e.data.get("sender", "?")
            lines.append(
                Line(str(sender), f"message to {e.data.get('to', '?')}", str(e.data.get("text", "")))
            )
    return lines


def find_moment(lines: list[Line], moment: str, context: int = 12) -> list[str]:
    """Excerpts around lines containing ``moment`` (case-insensitive), at most three."""
    needle = " ".join(moment.lower().split())
    excerpts = []
    used_until = -1
    for i, line in enumerate(lines):
        if i <= used_until or needle not in " ".join(line.text.lower().split()):
            continue
        lo, hi = max(0, i - context), min(len(lines), i + context // 2 + 1)
        excerpts.append("\n".join(f"[{x.agent}] {x.kind}: {x.text[:1200]}" for x in lines[lo:hi]))
        used_until = hi
        if len(excerpts) == 3:
            break
    return excerpts
