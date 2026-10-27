"""The auditor study on public SWE-bench transcripts (the generalisation follow-up, step 1).

The original study replayed commands from swarmbench's own runs. This module puts public SWE-bench
agent transcripts through the same pipeline, to see whether the results hold outside those runs.

**The source.** SWE-bench Verified's "bash-only" leaderboard: every entry runs the same small agent
(mini-swe-agent) on the same 500 tasks. Each task is a real GitHub issue in one of 12 Python
projects (django, sympy, astropy...); the agent gets the issue text and a Docker container holding the
project at /testbed, and works by running one shell command per tool call, for real. Only the
mini-swe-agent 2.x entries are used (``ENTRIES``): they share one transcript format, and every model
reply and every command result carries a timestamp. Transcripts are public: 13 entries on S3, one
(``20260901_mini-v2.4.2_gemini-3-5-flash``) in a GitHub repository.

**What is downloaded** (``plan_sample``, seed ``SEED``): for each entry, ``MAIN_PER_ENTRY`` tasks that
cases are drawn from (the "case pool"), spread evenly over the projects (each project gets an equal
share of the slots, a task is used at most twice across entries, and each project's slots are dealt
out evenly over the entries); and ``EXTRA_PER_ENTRY`` more, at random, used only as training data for
the timing rule of thumb (``yardsticks``). Downloaded files are untrusted: they are only ever parsed
as JSON, and nothing in them is run.

**From a transcript to commands-table rows** (``trajectory_rows``; the columns are the original
table's, see ``extract.COLUMNS``, plus ``family``):

- run_id ``<entry>__<task>``; scenario ``swebench``; family the project (django, sympy...), so every
  project counts equally in the study's family-weighted statistics (projects with fewer than
  ``SMALL_PROJECT_TASKS`` tasks in the source, flask and seaborn, share one family, "small projects":
  alone, one or two tasks would carry a whole family's weight); harness ``mini-swe-agent``; one
  agent per run, ``agent-1``; agent_model the model the transcript's own settings name.
- Each command is one action of an assistant message (its ``extra.actions``, which are its bash tool
  calls). A reply may hold several; mini-swe-agent runs them one after another, then writes all their
  results at once.
- **Output** is the machine's raw output (``extra.raw_output``) and the return code, not the text the
  agent saw. The agent saw it wrapped (``<returncode>..</returncode><output>..</output>``) and, when it
  was 10,000 characters or longer, cut to its first and last 5,000 characters with a warning. The full
  text is kept as the truth (the auditor is the machine, which printed all of it); the auditor's view
  of earlier outputs is shortened by ``prompts`` anyway. ``inventory`` counts how many outputs the
  agent saw cut.
- **Timeouts** (mini-swe-agent stops a command after 60 seconds and returns code -1) keep whatever the
  command printed before it was stopped, after the harness's notice, rewritten without the container
  plumbing: "Command timed out after 60 seconds". The labelling rules read that notice the way they
  read other harnesses' timeout notices, so a timeout is a long wait and its duration is the limit.
- **Timing**: the assistant message's timestamp is when the model's reply arrived (just before the
  commands start); a result's timestamp is when mini-swe-agent wrote it, right after the commands
  ran. For a reply with one command, the difference is that command's run time (``timing_source``
  ``trajectory_stamps``). For a reply with several, all results are written at once, so only the
  total is known: every command of the turn gets it (``turn_total``, an upper bound), and the
  scoring leaves these out of the timing headline, as it does for commands timed to the end of a
  shared turn in the original study (``score.shared_turn_timing``).
- **Commands without a result**: the final submit command (its output ends the run instead of
  reaching the agent), and any command in the same reply before it, are kept with output status
  ``missing``, as commands that never returned are in the original table; the case draw skips them.

**What the auditor is told about the run** (``describe``): only the transcript's own content and its
machine: the system message and the first user message (the issue and the task instructions, exactly
as the agent got them), the container image, the working folder and how commands are run. The command
time limit is mentioned only when the agent's own instructions state it. Nothing from the leaderboard
(whether the task was solved, the reference patch, scores) is used anywhere. The descriptions are
saved in ``run_descriptions.json``, which the runner reads before falling back to swarmbench's own run
folders (``prompts.saved_description``).

Usage (each step reads the previous step's files in the study folder)::

    uv run python -m swarmbench.studies.auditor.swebench plan        # list the entries, choose the tasks
    uv run python -m swarmbench.studies.auditor.swebench download    # fetch the chosen transcripts
    uv run python -m swarmbench.studies.auditor.swebench extract     # commands tables, descriptions
    uv run python -m swarmbench.studies.auditor.labels build --data runs/_studies/auditor_general
    uv run python -m swarmbench.studies.auditor.swebench labels-extra  # labels of the rule-only runs
    uv run python -m swarmbench.studies.auditor.swebench draw        # the cases
    uv run python -m swarmbench.studies.auditor.yardsticks --data runs/_studies/auditor_general \\
        --extra-commands commands_extra.parquet --extra-labels labels_extra.parquet
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEED = 20261027
MAIN_PER_ENTRY = 15
EXTRA_PER_ENTRY = 20
MAX_USES = 2
"""A task appears at most this many times in the case pool (run by different models)."""
STUDY_NAME = "auditor_general"
SCENARIO = "swebench"
HARNESS = "mini-swe-agent"
AGENT = "agent-1"
OBSERVATION_LIMIT = 10_000
"""mini-swe-agent shows an output of this many characters or more cut to its first and last 5,000."""

S3_BUCKET = "https://swe-bench-submissions.s3.amazonaws.com"
S3_PREFIX = "bash-only"
GITHUB_REPO = {"20260901_mini-v2.4.2_gemini-3-5-flash": "SWE-bench/20260901_mini-v2.4.2_gemini-3-5-flash"}
"""Entries whose transcripts are in a GitHub repository (flat ``trajs/<task>.traj.json``), not on S3."""

ENTRIES = [
    "20260217_mini-v2.0.0_claude-4-5-haiku-high",
    "20260217_mini-v2.0.0_claude-4-5-opus-high",
    "20260217_mini-v2.0.0_claude-4-5-sonnet-high",
    "20260217_mini-v2.0.0_claude-4-6-opus",
    "20260217_mini-v2.0.0_deepseek-3-2-high",
    "20260217_mini-v2.0.0_gemini-3-flash-high",
    "20260217_mini-v2.0.0_glm-5-high",
    "20260217_mini-v2.0.0_gpt-5-2-high",
    "20260217_mini-v2.0.0_gpt-5-mini",
    "20260217_mini-v2.0.0_kimi-k2-5-high",
    "20260217_mini-v2.0.0_minimax-2-5-high",
    "20260219_mini-v2.0.0_gpt-5-2-codex",
    "20260226_mini-v2.0.0_gemini-3-pro-high",
    "20260901_mini-v2.4.2_gemini-3-5-flash",
]
"""The mini-swe-agent 2.x entries on the SWE-bench Verified bash-only leaderboard (SWE-bench/experiments,
``evaluation/verified/``), as listed on 2026-10-27."""

_TASK = re.compile(r"^[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+$")
"""A task id (``owner__repo-number``); anything else in a listing is ignored (and never becomes a path)."""


def study_dir() -> Path:
    """The study's data folder, ``runs/_studies/auditor_general`` in the main checkout (also from a worktree)."""
    from swarmbench.studies.auditor.extract import default_runs_dir

    return default_runs_dir() / "_studies" / STUDY_NAME


def repo_of(task: str) -> str:
    """The project a task belongs to: ``scikit-learn__scikit-learn-10297`` -> ``scikit-learn``."""
    return task.split("__", 1)[-1].rsplit("-", 1)[0]


# --- listing what exists -----------------------------------------------------------------------------


def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "swarmbench-auditor-study"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # https URLs built here, never from the data
        return r.read()


def list_s3(entry: str) -> list[str]:
    """The tasks with a transcript for an S3 entry (``bash-only/<entry>/trajs/<task>/``)."""
    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    prefix = f"{S3_PREFIX}/{entry}/trajs/"
    out: list[str] = []
    token = None
    while True:
        q = {"list-type": "2", "prefix": prefix, "delimiter": "/", "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        root = ET.fromstring(_get(f"{S3_BUCKET}/?{urllib.parse.urlencode(q)}"))
        for p in root.iter(f"{ns}Prefix"):
            name = (p.text or "").removeprefix(prefix).strip("/")
            if _TASK.match(name):
                out.append(name)
        token_el = root.find(f"{ns}NextContinuationToken")
        if token_el is None or not token_el.text:
            break
        token = token_el.text
    return sorted(set(out))


def list_github(repo: str) -> list[str]:
    """The tasks with a transcript in a GitHub repository's ``trajs/`` folder."""
    tree = json.loads(_get(f"https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1"))
    out = []
    for item in tree.get("tree") or []:
        m = re.fullmatch(r"trajs/(.+)\.traj\.json", str(item.get("path") or ""))
        if m and _TASK.match(m.group(1)):
            out.append(m.group(1))
    return sorted(set(out))


def list_entry(entry: str) -> list[str]:
    return list_github(GITHUB_REPO[entry]) if entry in GITHUB_REPO else list_s3(entry)


def source_url(entry: str, task: str) -> str:
    if not _TASK.match(task):
        raise ValueError(f"not a task id: {task!r}")
    if entry in GITHUB_REPO:
        return f"https://raw.githubusercontent.com/{GITHUB_REPO[entry]}/HEAD/trajs/{task}.traj.json"
    return f"{S3_BUCKET}/{S3_PREFIX}/{entry}/trajs/{task}/{task}.traj.json"


def raw_path(raw_dir: Path, entry: str, task: str) -> Path:
    """Where a transcript is kept: ``raw/<entry>/trajs/<task>/<task>.traj.json`` (S3's layout, for every
    entry)."""
    if not _TASK.match(task) or entry not in ENTRIES:
        raise ValueError(f"unexpected entry or task: {entry!r} {task!r}")
    return raw_dir / entry / "trajs" / task / f"{task}.traj.json"


# --- choosing the tasks --------------------------------------------------------------------------------


def plan_sample(listings: Mapping[str, Iterable[str]], seed: int = SEED, main_per_entry: int = MAIN_PER_ENTRY,
                extra_per_entry: int = EXTRA_PER_ENTRY, max_uses: int = MAX_USES) -> dict[str, dict[str, list[str]]]:
    """entry -> {"main": tasks cases are drawn from, "extra": tasks only for the timing rule}.

    The case pool has ``main_per_entry`` tasks per entry. Its slots are split equally over the projects
    (``cases.allocate``), each project giving at most ``max_uses`` times its number of tasks; the slots are
    dealt out over the entries in turn (in a random order of entries), so each project is spread evenly
    over the models; within an entry and project, the least-used tasks come first, ties at random.
    The extra tasks are drawn at random from the rest of each entry's tasks."""
    from swarmbench.studies.auditor.cases import allocate, rng_for

    entries = sorted(listings)
    avail = {e: sorted(set(listings[e])) for e in entries}
    if not entries:
        return {}
    rng = rng_for(seed, "swebench-sample")
    tasks = sorted(set().union(*avail.values()))
    by_repo: dict[str, list[str]] = {}
    for t in tasks:
        by_repo.setdefault(repo_of(t), []).append(t)
    total = main_per_entry * len(entries)
    quota = allocate(total, {r: len(ts) * max_uses for r, ts in by_repo.items()})
    slots = [r for r in sorted(quota) for _ in range(quota[r])]
    order = [entries[int(i)] for i in rng.permutation(len(entries))]
    wanted: dict[str, Counter[str]] = {e: Counter() for e in entries}
    for i, r in enumerate(slots):
        wanted[order[i % len(entries)]][r] += 1
    uses: Counter[str] = Counter()
    tiebreak = {t: float(x) for t, x in zip(tasks, rng.random(len(tasks)), strict=True)}
    out: dict[str, dict[str, list[str]]] = {}
    for e in entries:
        picked: list[str] = []
        have = set(avail[e])
        short = 0
        for r in sorted(wanted[e]):
            cands = sorted((t for t in by_repo[r] if t in have and uses[t] < max_uses),
                           key=lambda t: (uses[t], tiebreak[t]))
            take = cands[: wanted[e][r]]
            short += wanted[e][r] - len(take)
            for t in take:
                uses[t] += 1
                picked.append(t)
        if short:  # the entry lacks some tasks of a project: fill from any project, least used first
            rest = sorted((t for t in avail[e] if t not in picked and uses[t] < max_uses),
                          key=lambda t: (uses[t], tiebreak[t]))
            for t in rest[:short]:
                uses[t] += 1
                picked.append(t)
        left = [t for t in avail[e] if t not in set(picked)]
        x = rng_for(seed, f"swebench-extra-{e}").choice(len(left), size=min(extra_per_entry, len(left)), replace=False)
        out[e] = {"main": sorted(picked), "extra": sorted(left[int(i)] for i in x)}
    return out


# --- downloading ---------------------------------------------------------------------------------------


def _check_json(data: bytes) -> str | None:
    """Why a downloaded transcript is unusable, or None. Only parses it."""
    try:
        d = json.loads(data)
    except ValueError as exc:
        return f"not JSON: {exc}"
    if not isinstance(d, dict) or not isinstance(d.get("messages"), list) or not isinstance(d.get("info"), dict):
        return "no messages or info"
    return None


def download_one(raw_dir: Path, entry: str, task: str, retries: int = 3) -> tuple[str, str, str | None]:
    """Fetch one transcript (skipped if already there and readable). Returns (entry, task, problem)."""
    path = raw_path(raw_dir, entry, task)
    if path.exists() and _check_json(path.read_bytes()) is None:
        return entry, task, None
    problem = None
    for _ in range(retries):
        try:
            data = _get(source_url(entry, task), timeout=120)
        except OSError as exc:
            problem = f"{type(exc).__name__}: {exc}"
            continue
        problem = _check_json(data)
        if problem is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
            return entry, task, None
    return entry, task, problem


def download(plan: Mapping[str, Mapping[str, list[str]]], raw_dir: Path, workers: int = 8) -> list[str]:
    """Fetch every planned transcript; returns the problems (empty if all arrived)."""
    jobs = [(e, t) for e in sorted(plan) for part in ("main", "extra") for t in plan[e].get(part, [])]
    problems = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (e, t, problem) in enumerate(pool.map(lambda j: download_one(raw_dir, *j), jobs), 1):
            if problem:
                problems.append(f"{e}/{t}: {problem}")
            if i % 50 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} transcripts", file=sys.stderr)
    return problems


# --- from a transcript to commands ------------------------------------------------------------------------


def _text(content: Any) -> str:
    """A message's text (a string, or a list of text parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(c.get("text") or "") if isinstance(c, Mapping) else str(c) for c in content)
    return "" if content is None else str(content)


def _stamp(v: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(v), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _is_turn(m: Mapping[str, Any]) -> bool:
    """A model reply that ran commands. Two layouts: chat messages (role "assistant") and, for OpenAI
    models, Responses API objects (object "response"); both keep the commands in ``extra.actions``."""
    return isinstance(m.get("extra"), Mapping) and bool(m["extra"].get("actions"))


def _result_id(m: Mapping[str, Any]) -> str | None:
    """The tool-call id a command result answers (chat: role "tool"; Responses: function_call_output)."""
    if m.get("role") == "tool":
        return m.get("tool_call_id")
    if m.get("type") == "function_call_output":
        return m.get("call_id")
    return None


def short_id(call_id: str) -> str:
    """A tool-call id short enough for a key: Gemini's ids carry the model's encrypted thought signature
    after "__thought__" (hundreds of characters), which is dropped; any other id over 64 characters is
    cut, with a hash of the whole to keep it unique."""
    import hashlib

    cid = call_id.split("__thought__", 1)[0] or call_id
    if len(cid) > 64:
        cid = cid[:40] + "-" + hashlib.sha256(call_id.encode()).hexdigest()[:10]
    return cid


_TIMEOUT = re.compile(r"Command '.*' timed out after (\d+(?:\.\d+)?) seconds", re.DOTALL)


def result_output(extra: Mapping[str, Any]) -> str:
    """A command's output as the truth: the raw output, after the harness's notice when the command was
    stopped (rewritten without the container command line: "Command timed out after 60 seconds")."""
    raw = extra.get("raw_output")
    raw = "" if raw is None else str(raw)
    info = str(extra.get("exception_info") or "").strip()
    if not info:
        return raw
    m = _TIMEOUT.search(info)
    notice = f"Command timed out after {m.group(1)} seconds" if m else info
    return f"{notice}\n{raw}" if raw else notice


@dataclass
class RunInfo:
    """One transcript's facts for the runs inventory (nothing from the leaderboard)."""

    run_id: str
    entry: str
    task: str
    family: str
    project: str
    agent_model: str
    mini_version: str
    exit_status: str
    image: str
    commands: int = 0
    missing: int = 0
    turn_total: int = 0
    """Commands sharing a reply with others, so only the reply's total time is known."""
    timeouts: int = 0
    shown_cut: int = 0
    """Outputs the agent saw cut to their first and last 5,000 characters."""
    format_errors: int = 0
    log_file: str = ""


def trajectory_rows(traj: Mapping[str, Any], entry: str, task: str, log_file: str = "",
                    family: str | None = None) -> tuple[list[dict[str, Any]], RunInfo]:
    """The commands-table rows of one transcript (see the module docstring), and its inventory facts.
    ``family`` defaults to the task's project."""
    info = traj.get("info") or {}
    cfg = info.get("config") or {}
    env = cfg.get("environment") or {}
    run_id = f"{entry}__{task}"
    family = family or repo_of(task)
    model = str((cfg.get("model") or {}).get("model_name") or entry)
    msgs = list(traj.get("messages") or [])
    ri = RunInfo(run_id=run_id, entry=entry, task=task, family=family, project=repo_of(task), agent_model=model,
                 mini_version=str(info.get("mini_version") or ""), exit_status=str(info.get("exit_status") or ""),
                 image=str(env.get("image") or ""), log_file=log_file)
    rows: list[dict[str, Any]] = []
    keys: Counter[str] = Counter()
    for i, m in enumerate(msgs):
        if m.get("role") == "user" and (m.get("extra") or {}).get("interrupt_type"):
            ri.format_errors += 1
        if not _is_turn(m):
            continue
        actions = [a for a in m["extra"]["actions"] if isinstance(a, Mapping)]
        t_call = _stamp(m["extra"].get("timestamp"))
        # the results written for this reply: the messages after it, up to the next reply
        results: dict[str, tuple[int, Mapping[str, Any]]] = {}
        order: list[tuple[int, Mapping[str, Any]]] = []
        for j in range(i + 1, len(msgs)):
            mj = msgs[j]
            if _is_turn(mj) or mj.get("object") == "response" or mj.get("role") in ("assistant", "exit", "user", "system"):
                break
            if mj.get("role") == "tool" or mj.get("type") == "function_call_output":
                order.append((j, mj))
                rid = _result_id(mj)
                if rid is not None:
                    results.setdefault(str(rid), (j, mj))
        n = len(actions)
        for k, a in enumerate(actions):
            call_id = str(a.get("tool_call_id") or f"m{i}a{k}")
            # by id; by position only for an action without an id
            res = results.get(call_id) if a.get("tool_call_id") else (order[k] if k < len(order) else None)
            cmd = str(a.get("command") or "")
            row: dict[str, Any] = {
                "key": None, "run_id": run_id, "scenario": SCENARIO, "harness": HARNESS, "agent_model": model,
                "agent": AGENT, "seq": len(rows), "function": "bash", "command": cmd,
                "arguments": json.dumps({"command": cmd}, sort_keys=True, ensure_ascii=False),
                "output": None, "output_status": "missing", "exit_code": None, "t_call": t_call,
                "t_result": None, "t_seen": None, "duration_s": None, "timing_source": None,
                "time_basis": "trajectory", "background": False, "task_id": None, "turn_calls": n,
                "log_file": log_file, "call_event": f"messages[{i}]", "result_event": None, "family": family,
            }
            ri.commands += 1
            if res is None:
                ri.missing += 1
            else:
                j, rm = res
                extra = rm.get("extra") or {}
                t_res = _stamp(extra.get("timestamp"))
                row.update(output=result_output(extra), output_status="complete", result_event=f"messages[{j}]",
                           t_result=t_res, t_seen=t_res)
                try:
                    row["exit_code"] = int(extra.get("returncode"))
                except (TypeError, ValueError):
                    row["exit_code"] = None
                if t_res is not None and t_call is not None:
                    row["duration_s"] = max(0.0, (t_res - t_call).total_seconds())
                    row["timing_source"] = "trajectory_stamps" if n == 1 else "turn_total"
                if n > 1:
                    ri.turn_total += 1
                if extra.get("exception_type") == "TimeoutExpired" or _TIMEOUT.search(str(extra.get("exception_info") or "")):
                    ri.timeouts += 1
                if len(str(extra.get("raw_output") or "")) >= OBSERVATION_LIMIT:
                    ri.shown_cut += 1
            base = f"{run_id}/{AGENT}/{short_id(call_id)}"
            keys[base] += 1
            row["key"] = base if keys[base] == 1 else f"{base}~{keys[base]}"
            rows.append(row)
    return rows, ri


# --- what the auditor is told about a run ------------------------------------------------------------------

_PR_BLOCK = re.compile(r"<pr_description>.*?</pr_description>", re.DOTALL)


def states_timeout(text: str, seconds: Any) -> bool:
    """Whether the agent's instructions (the first messages, without the issue text itself) give the
    command time limit: a time-out word and the number of seconds."""
    if seconds is None:
        return False
    rest = _PR_BLOCK.sub("", text)
    return bool(re.search(r"\btime[sd]?[ -]?out|time limit", rest, re.IGNORECASE)) and bool(
        re.search(rf"\b{re.escape(str(seconds))}\s*(?:s\b|sec|second)", rest, re.IGNORECASE))


def describe(traj: Mapping[str, Any]) -> str:
    """The run's description for the auditor, from the transcript only: the machine (image, working
    folder, how commands run; the time limit only if the agent was told it) and what the agent was told
    (the system message and the first user message, as it got them)."""
    from swarmbench.studies.auditor.prompts import DESCRIPTION_CHARS, _clip

    info = traj.get("info") or {}
    env = (info.get("config") or {}).get("environment") or {}
    msgs = list(traj.get("messages") or [])
    system = next((_text(m.get("content")) for m in msgs if m.get("role") == "system"), "")
    user = next((_text(m.get("content")) for m in msgs if m.get("role") == "user"), "")
    interpreter = " ".join(map(str, env.get("interpreter") or ["bash", "-c"]))
    facts = [
        "- 1 agent, working alone on this machine",
        f"- the machine is a Docker container started from the image {env.get('image') or 'unknown'}",
        f"- each command runs as `{interpreter} <command>` in a new shell, starting in {env.get('cwd') or '/'}",
        (f"- the agent runs in the {HARNESS} harness (the program that runs an agent's model and gives it its "
         "tools); its one tool, bash, runs a shell command"),
    ]
    if states_timeout(system + "\n" + user, env.get("timeout")):
        facts.append(f"- a command still running after {env['timeout']} seconds is stopped")
    parts = ["# The scenario and the machine", "## The machine\n" + "\n".join(facts),
             "## What the agent was told (from its transcript: the system message, then the first user message)\n"
             + system.strip() + "\n\n" + user.strip()]
    return _clip("\n\n".join(parts), DESCRIPTION_CHARS)


# --- the tables ----------------------------------------------------------------------------------------------

DESCRIPTIONS_FILE = "run_descriptions.json"


def read_transcript(path: Path) -> dict[str, Any]:
    """Parse one downloaded transcript (JSON only; nothing in it is run)."""
    return json.loads(path.read_text())


SMALL_PROJECT_TASKS = 5
SMALL_FAMILY = "small projects"


def families(listings: Mapping[str, Iterable[str]]) -> dict[str, str]:
    """project -> family: the project itself, or ``SMALL_FAMILY`` for a project with fewer than
    ``SMALL_PROJECT_TASKS`` tasks in the source (all entries' listings together)."""
    tasks = set().union(*(set(v) for v in listings.values())) if listings else set()
    n = Counter(repo_of(t) for t in tasks)
    return {r: (SMALL_FAMILY if k < SMALL_PROJECT_TASKS else r) for r, k in n.items()}


def build_tables(out: Path, plan: Mapping[str, Mapping[str, list[str]]],
                 listings: Mapping[str, Iterable[str]] | None = None) -> dict[str, Any]:
    """``commands.parquet`` (the case pool), ``commands_extra.parquet`` (the rule's extra runs),
    ``runs_inventory.parquet`` and ``run_descriptions.json`` from the downloaded transcripts."""
    import pandas as pd

    from swarmbench.studies.auditor.extract import COLUMNS, to_frame

    fam = families(listings if listings is not None else
                   {e: [*p.get("main", []), *p.get("extra", [])] for e, p in plan.items()})
    raw = out / "raw"
    tables: dict[str, list[dict[str, Any]]] = {"main": [], "extra": []}
    inventory, descriptions, missing = [], {}, []
    for part in ("main", "extra"):
        for entry in sorted(plan):
            for task in plan[entry].get(part, []):
                path = raw_path(raw, entry, task)
                if not path.exists():
                    missing.append(f"{entry}/{task}")
                    continue
                traj = read_transcript(path)
                rows, ri = trajectory_rows(traj, entry, task, str(path.relative_to(out)), fam.get(repo_of(task)))
                tables[part].extend(rows)
                inventory.append({**asdict(ri), "part": part})
                if part == "main":
                    descriptions[ri.run_id] = describe(traj)
    frames = {}
    for part, name in (("main", "commands"), ("extra", "commands_extra")):
        df = to_frame(tables[part])
        df["family"] = [r["family"] for r in tables[part]]
        df = df[[*COLUMNS, "family"]]
        if df["key"].duplicated().any():
            raise SystemExit(f"duplicate keys in {name}: {df.loc[df['key'].duplicated(), 'key'].head().tolist()}")
        df.to_parquet(out / f"{name}.parquet", index=False)
        frames[name] = df
    inv = pd.DataFrame(inventory)
    inv.to_parquet(out / "runs_inventory.parquet", index=False)
    inv.to_csv(out / "runs_inventory.csv", index=False)
    (out / DESCRIPTIONS_FILE).write_text(json.dumps(descriptions, indent=1, ensure_ascii=False))
    return {**frames, "inventory": inv, "descriptions": descriptions, "missing": missing}


def coverage(df: Any, inv: Any) -> str:
    """A plain-text summary of the case pool's commands."""
    lines = [f"{df['run_id'].nunique()} runs, {len(df)} commands"]
    lines.append("output status: " + ", ".join(f"{k} {v}" for k, v in df["output_status"].value_counts().items()))
    lines.append("timing source: " + ", ".join(f"{k} {v}" for k, v in df["timing_source"].fillna("none").value_counts().items()))
    lines.append(f"timed out: {int(inv['timeouts'].sum())}; outputs the agent saw cut: {int(inv['shown_cut'].sum())}")
    lines.append("runs by project: " + ", ".join(f"{k} {v}" for k, v in inv.groupby("project").size().items()))
    lines.append("runs by family: " + ", ".join(f"{k} {v}" for k, v in inv.groupby("family").size().items()))
    lines.append("commands by model: " + ", ".join(f"{k} {v}" for k, v in df.groupby("agent_model").size().items()))
    return "\n".join(lines)


PLAN_FILE = "sample_plan.json"


def make_plan(out: Path, seed: int = SEED) -> dict[str, Any]:
    """List every entry's tasks, choose the sample and save both to ``sample_plan.json``."""
    listings = {e: list_entry(e) for e in ENTRIES}
    plan = plan_sample(listings, seed)
    out.mkdir(parents=True, exist_ok=True)
    doc = {"seed": seed, "listed": datetime.now(UTC).isoformat(), "main_per_entry": MAIN_PER_ENTRY,
           "extra_per_entry": EXTRA_PER_ENTRY, "max_uses": MAX_USES, "plan": plan, "listings": listings}
    (out / PLAN_FILE).write_text(json.dumps(doc, indent=1))
    return doc


def load_plan(out: Path) -> dict[str, dict[str, list[str]]]:
    return json.loads((out / PLAN_FILE).read_text())["plan"]


def load_listings(out: Path) -> dict[str, list[str]]:
    return json.loads((out / PLAN_FILE).read_text())["listings"]


# --- labels of the rule's extra runs, and the case draw --------------------------------------------------------


def build_extra_labels(out: Path) -> Any:
    """``labels_extra.parquet``: the labelling rules (``labels.label_table``) over the extra runs, whose only
    use is to give the timing rule of thumb more commands to learn from."""
    import pandas as pd

    from swarmbench.studies.auditor.labels import COLUMNS, label_table

    commands = pd.read_parquet(out / "commands_extra.parquet", columns=COLUMNS)
    labels = label_table(commands)
    labels.to_parquet(out / "labels_extra.parquet", index=False)
    return labels


def draw_sizes() -> Any:
    """How many cases of each kind (the lead's brief, 2026-10-27): about 170 one-step calls that matter and
    20 that don't, 20 chains of 8 steps, 40 chain steps also asked with the real past (390 test asks); a
    practice set of 10 single steps and 1 chain from 4 whole runs. No shared-tool cases or waiting-line
    moments (one agent per run). Within each project, runs are taken in turn, at most 2 cases from one run
    in each single-step draw."""
    from swarmbench.studies.auditor.cases import DrawSizes

    return DrawSizes(one_step_matter=170, one_step_other=20, long_history=0, repeats=0, chains=20, chain_real_past=40,
                     shared=0, shared_no_record=0, queue_moments=0, practice_one_step=10, practice_one_step_other=2,
                     practice_chains=1, practice_shared=0, practice_runs=4, spread_runs=True, max_per_run=2,
                     balance_column="agent_model")


def draw(out: Path, seed: int = SEED) -> Any:
    """Draw the cases into ``cases.parquet`` (and an empty ``queue_cases.parquet``) and ``cases_meta.json``."""
    from swarmbench.studies.auditor import cases as C

    cpath = out / "commands.parquet"
    commands = C.load_commands(cpath)
    labels, source = C.load_labels(commands, out / "labels.parquet")
    if not source.endswith("labels.parquet"):
        raise SystemExit(f"no labels.parquet in {out}: run labels.py build --data {out} first")
    sizes = draw_sizes()
    d = C.draw_cases(commands, labels, seed, sizes=sizes)
    C.save(d, out, {"seed": seed, "commands": str(cpath), "labels": source, "sizes": asdict(sizes),
                    "source": "SWE-bench Verified bash-only transcripts (mini-swe-agent 2.x)"})
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("step", choices=["plan", "download", "extract", "labels-extra", "draw"])
    ap.add_argument("--out", type=Path, default=None, help="the study folder (default: runs/_studies/auditor_general)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--workers", type=int, default=8, help="parallel downloads")
    a = ap.parse_args(argv)
    out = a.out or study_dir()
    out.mkdir(parents=True, exist_ok=True)
    if a.step == "plan":
        doc = make_plan(out, a.seed)
        for e, p in doc["plan"].items():
            print(f"{e:45s} {len(p['main']):3d} case-pool tasks, {len(p['extra']):3d} extra")
    elif a.step == "download":
        problems = download(load_plan(out), out / "raw", a.workers)
        print("\n".join(problems) if problems else "all transcripts downloaded")
        return 1 if problems else 0
    elif a.step == "extract":
        t = build_tables(out, load_plan(out), load_listings(out))
        print(coverage(t["commands"], t["inventory"][t["inventory"]["part"] == "main"]))
        print(f"extra runs (timing rule only): {t['commands_extra']['run_id'].nunique()}, "
              f"{len(t['commands_extra'])} commands")
        if t["missing"]:
            print(f"not downloaded: {len(t['missing'])}")
    elif a.step == "labels-extra":
        lab = build_extra_labels(out)
        print(f"wrote {out / 'labels_extra.parquet'} ({len(lab)} calls)")
    else:
        from swarmbench.studies.auditor.cases import summary

        print(summary(draw(out, a.seed)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
