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

from swarmbench.config import parse_duration
from swarmbench.design.signals import (
    Level,
    Moment,
    Screen,
    TurningPoint,
    leads_of,
    levels_of,
    little_happened,
    moment_of,
    screen_of,
    short_time_agents,
    turning_points_of,
)
from swarmbench.paths import RunDir
from swarmbench.types import JudgeReport, MonitorFlag

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
# report.json fields that render() prints itself; everything else (turning points, leads,
# behaviours and whatever the judge adds next) is passed to the model as YAML.
_RENDERED = {
    "run_id", "scenario", "sample_id", "epoch", "verdict", "headline", "summary", "concerns",
    "outcome", "stats", "cost", "coverage", "eval_awareness", "realism_notes",
}  # fmt: skip


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
    raw_reports: list[dict[str, Any]] = field(default_factory=list)
    """report.json entries as written, including fields newer than JudgeReport."""
    moments: list[Moment] = field(default_factory=list)
    levels: list[Level] = field(default_factory=list)
    turning_points: list[TurningPoint] = field(default_factory=list)
    leads: list[str] = field(default_factory=list)
    short_agents: list[str] = field(default_factory=list)
    quiet: list[str] = field(default_factory=list)
    """The judge's "little happened" notes."""
    screen: Screen | None = None
    time_limit_s: float | None = None

    @property
    def empty(self) -> bool:
        return not (self.reports or self.raw_reports or self.flags or self.scanners or self.screen)


def collect(run_dir: RunDir) -> RunEvidence:
    ev = RunEvidence(run_id=run_dir.run_id)
    if not run_dir.root.is_dir():
        ev.problems.append(f"run folder {run_dir.root} does not exist")
        return ev
    # Each reader is isolated: one damaged file must not hide the others.
    for name, reader in (
        ("scenario.yaml", _read_settings),
        ("report.json", _read_reports),
        ("monitor.jsonl", _read_monitor),
        ("scans/", _read_scans),
        ("screen results", _read_screen),
    ):
        try:
            reader(run_dir, ev)
        except Exception as e:
            ev.problems.append(f"{name} could not be read: {str(e)[:200]}")
    return ev


def _read_settings(run_dir: RunDir, ev: RunEvidence) -> None:
    if not run_dir.scenario.exists():
        return
    data = yaml.safe_load(run_dir.scenario.read_text()) or {}
    if not isinstance(data, dict):
        return
    try:
        ev.time_limit_s = float(parse_duration(data.get("time_limit", 3600)))
    except ValueError:
        ev.time_limit_s = None
    swarm = data.get("swarm") or {}
    swarm = swarm if isinstance(swarm, dict) else {}
    keys = ["agents", "model", "effort", "harness", "messaging", "token_budget"]
    parts = [f"{k}={swarm[k]}" for k in keys if swarm.get(k) is not None]
    if isinstance(data.get("teams"), list):
        parts.append("teams=" + ",".join(str(t.get("name")) for t in data["teams"] if isinstance(t, dict)))
    ev.settings = ", ".join(parts)


def _read_reports(run_dir: RunDir, ev: RunEvidence) -> None:
    path = run_dir.report_json
    if not path.exists():
        ev.problems.append("no report.json (the judge has not run, or failed)")
        return
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        ev.problems.append(f"report.json could not be read: {str(e)[:300]}")
        return
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        ev.problems.append("report.json holds no reports")
        return
    adapter = TypeAdapter(JudgeReport)
    for i, raw in enumerate(data, 1):
        if not isinstance(raw, dict):
            ev.problems.append(f"report.json entry {i} is not an object")
            continue
        ev.raw_reports.append(raw)
        try:
            ev.reports.append(adapter.validate_python(raw))
        except ValidationError as e:
            ev.problems.append(f"report.json entry {i} could not be read: {str(e)[:300]}")
        moment = moment_of(raw)
        if moment is not None:
            ev.moments.append(moment)
        ev.levels += levels_of(raw)
        ev.turning_points += turning_points_of(raw)
        ev.leads += leads_of(raw)
        ev.short_agents += short_time_agents(raw)
        if little_happened(raw):
            ev.quiet.append(little_happened(raw))


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
        where = summary_file.relative_to(run_dir.root)
        try:
            data = json.loads(summary_file.read_text())
            scanners = data.get("scanners") or {}
            counts = {
                str(name): {key: int(s.get(key, 0) or 0) for key in ("scans", "results", "errors")}
                for name, s in scanners.items()
            }
        except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
            ev.problems.append(f"unreadable scanner summary {where}")
            continue
        if data.get("complete") is False:
            ev.problems.append(f"scan {where.parent} did not finish, so its counts are partial")
        for name, c in counts.items():
            total = ev.scanners.setdefault(name, {"scans": 0, "results": 0, "errors": 0})
            for key in total:
                total[key] += c[key]
        ev.scanner_hits.update(_scanner_explanations(summary_file.parent))


def _read_screen(run_dir: RunDir, ev: RunEvidence) -> None:
    """A ``swarm screen`` label, from screen.json or status.json (location still settling)."""
    for path in (run_dir.root / "screen.json", run_dir.status):
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        if path == run_dir.status and isinstance(data, dict):
            data = data.get("screen") or data.get("screen_label")
        found = screen_of(data)
        if found:
            ev.screen = found
            return


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
    except Exception:
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
    for raw in ev.raw_reports:
        extra = {k: v for k, v in raw.items() if k not in _RENDERED and v not in (None, [], {}, "")}
        if extra:
            text = yaml.safe_dump(extra, sort_keys=False, allow_unicode=True, width=100)
            lines.append("\n## Further judge fields (turning points, leads, how-far levels and so on)")
            lines.append(text[:6000].rstrip() + ("\n[... trimmed ...]" if len(text) > 6000 else ""))
    if ev.screen:
        reasons = "; ".join(ev.screen.reasons)
        lines.append(f"\n## Screening label: {ev.screen.label}" + (f" ({reasons})" if reasons else ""))
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
