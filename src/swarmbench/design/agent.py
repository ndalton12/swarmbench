"""``swarm design``: start a coding agent that designs a scenario by following the design skill.

The design instructions live in one guide, ``.claude/skills/design-scenario/SKILL.md``. In Claude
Code it is the ``/design-scenario`` skill; ``swarm design`` starts a headless Claude Code (``claude
-p``) or Codex (``codex exec``) session that follows the same guide.

Each session works in its own folder, ``runs/designs/<time>-<kind>-<id>/work``: a copy of the
repository's ``docs/``, ``scenarios/``, ``README.md`` and the skill, never the repository itself.
When it ends, only scenario folders that are new are copied into the repository's
``scenarios/``; any other change the agent made is listed, not applied. While it runs:

- ``swarm`` on its PATH is this installation, and its runs folder is the session's own;
- ``SWARMBENCH_DESIGN_SESSION`` is set, so commands that spend money (run, screen, experiment,
  judge, digest) refuse anything but a dry run;
- Claude Code may only read and write files, run read-only ``swarm`` commands and Python (to test
  the tools it writes), and look at files; it runs under a dollar cap. Codex runs in its
  workspace-write sandbox, which keeps writes inside the working folder; it has no dollar cap.

The agent runs in its own process group, which is stopped if ``swarm design`` ends early. Its
output is shown as it works and saved in the session folder (Claude Code's as a stream of events,
``session.jsonl``, plus a readable ``session.log``).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL = Path(".claude/skills/design-scenario/SKILL.md")
AGENTS = ("claude", "codex")
DEFAULT_AGENT = "claude"
DEFAULT_MAX_COST = 15.0
SESSION_ENV = "SWARMBENCH_DESIGN_SESSION"
COPIED = ["docs", "scenarios", "README.md", str(SKILL.parent)]
"""What the agent's working folder starts with, relative to the repository."""

CLAUDE_TOOLS = [
    "Read", "Glob", "Grep", "Write", "Edit", "Skill",
    "Bash(swarm check *)", "Bash(swarm design evidence *)", "Bash(swarm report *)", "Bash(swarm prices show*)",
    "Bash(python3 *)", "Bash(ls *)", "Bash(mkdir *)", "Bash(cat *)", "Bash(head *)", "Bash(tail *)",
    "Bash(wc *)", "Bash(diff *)",
]  # fmt: skip
"""What a headless Claude Code designer may do without asking: read and write files, run read-only
swarmbench commands and Python (to test its tools), and look at files."""

ALONE = (
    "You are running without a person to answer questions: where the request is ambiguous, choose, and "
    "record the choice and why in design_log.md.\n\n"
    "This folder is a copy of the repository's docs, scenarios and the skill. Write the new scenario under "
    "scenarios/; only new scenario folders are kept. Run swarmbench as `swarm` (it is on PATH), not "
    "`uv run swarm`. Real runs are disabled here; `swarm check` and dry runs work."
)


def new_task(idea: str) -> str:
    return (
        f"Follow the design-scenario skill ({SKILL}; read it first) to design a new swarmbench "
        f"scenario from this request:\n\n{idea}\n\n{ALONE}"
    )


def iterate_task(scenario: Path, run_dirs: list[Path]) -> str:
    listed = "\n".join(f"- {r}" for r in run_dirs)
    return (
        f"Follow the design-scenario skill ({SKILL}; read it first, including 'Revising a scenario "
        f"after runs') to revise the scenario {scenario} using what these runs showed (read them with "
        f"`swarm design evidence <run>` and `swarm report <run>`):\n\n{listed}\n\n{ALONE}"
    )


def moment_task(run_dir: Path, moment: str, scenario: Path | None) -> str:
    source = f"The run came from the scenario {scenario}. " if scenario else ""
    return (
        f"Follow the design-scenario skill ({SKILL}; read it first, including 'Building a scenario "
        f"from a moment in a run') to build a new scenario from this moment in run {run_dir}:\n\n"
        f"{moment}\n\n{source}{ALONE}"
    )


def command(
    agent: str,
    task: str,
    *,
    model: str | None = None,
    max_cost: float | None = DEFAULT_MAX_COST,
    last_message: Path | None = None,
    workdir: Path = REPO_ROOT,
    readable: list[Path] | None = None,
) -> list[str]:
    """The command line that starts the agent in ``workdir``; ``readable`` are extra folders it
    may read (past runs)."""
    if agent == "claude":
        cmd = ["claude", "-p", task, "--permission-mode", "acceptEdits", "--allowedTools", *CLAUDE_TOOLS,
               "--output-format", "stream-json", "--verbose"]  # fmt: skip
        for folder in readable or []:
            cmd += ["--add-dir", str(folder)]
        if max_cost is not None:
            cmd += ["--max-budget-usd", f"{max_cost:g}"]
        if model:
            cmd += ["--model", model]
        return cmd
    if agent == "codex":
        cmd = ["codex", "exec", "--sandbox", "workspace-write", "--cd", str(workdir),
               "-c", "shell_environment_policy.inherit=all"]  # fmt: skip
        if last_message is not None:
            cmd += ["--output-last-message", str(last_message)]
        if model:
            cmd += ["--model", model]
        return [*cmd, task]
    raise ValueError(f"unknown agent {agent!r} (choose from {', '.join(AGENTS)})")


# --- the working copy ---------------------------------------------------------------------------------


def new_session(kind: str, repo: Path = REPO_ROOT) -> Path:
    """A session folder of its own: ``runs/designs/<time>-<kind>-<id>``, created exclusively."""
    base = repo / "runs" / "designs"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H%M%S")
    while True:
        folder = base / f"{stamp}-{kind}-{secrets.token_hex(2)}"
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue


def make_workdir(session: Path, repo: Path = REPO_ROOT, extra_scenarios: list[Path] | None = None) -> Path:
    """Copy what the agent needs into ``session/work``. ``extra_scenarios``: scenario folders from
    outside the repository's scenarios/ (copied in under their own names)."""
    work = session / "work"
    work.mkdir()
    ignore = shutil.ignore_patterns("__pycache__", ".DS_Store", ".pytest_cache")
    for rel in COPIED:
        src = repo / rel
        if src.is_dir():
            shutil.copytree(src, work / rel, ignore=ignore)
        elif src.is_file():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, work / rel)
    for folder in extra_scenarios or []:
        target = work / "scenarios" / folder.name
        if not target.exists():
            shutil.copytree(folder, target, ignore=ignore)
    (work / "runs").mkdir(exist_ok=True)
    return work


def fingerprint(root: Path) -> dict[str, str]:
    """Every file under ``root`` (except its runs/), with a digest of its contents."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if (
            path.is_file()
            and not path.is_symlink()
            and not rel.startswith("runs/")
            and "__pycache__" not in rel
        ):
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


@dataclass
class Changes:
    new_folders: list[str] = field(default_factory=list)
    """New folders directly under scenarios/."""
    other: list[str] = field(default_factory=list)
    """Every other change, e.g. "changed docs/realism.md"."""


def changes(before: dict[str, str], after: dict[str, str], scenarios_before: set[str]) -> Changes:
    out = Changes()
    new = set()
    for rel in sorted(set(before) | set(after)):
        if before.get(rel) == after.get(rel):
            continue
        parts = rel.split("/")
        if (
            len(parts) > 2
            and parts[0] == "scenarios"
            and parts[1] not in scenarios_before
            and rel not in before
        ):
            new.add(parts[1])
            continue
        what = "added" if rel not in before else "deleted" if rel not in after else "changed"
        out.other.append(f"{what} {rel}")
    out.new_folders = sorted(new)
    return out


def publish(work: Path, names: list[str], repo: Path = REPO_ROOT) -> tuple[list[Path], list[str]]:
    """Copy new scenario folders into the repository. Returns (copied, skipped because they exist)."""
    copied, skipped = [], []
    for name in names:
        target = repo / "scenarios" / name
        if target.exists():
            skipped.append(name)
            continue
        shutil.copytree(work / "scenarios" / name, target)
        copied.append(target)
    return copied, skipped


# --- running it ---------------------------------------------------------------------------------------


def describe_event(line: str) -> list[str]:
    """Readable lines for one event of Claude Code's stream-json output (anything else as it is)."""
    try:
        event = json.loads(line)
    except ValueError:
        return [line.rstrip("\n")] if line.strip() else []
    if not isinstance(event, dict):
        return []
    kind = event.get("type")
    if kind == "assistant":
        out = []
        for part in (event.get("message") or {}).get("content") or []:
            if part.get("type") == "text" and str(part.get("text", "")).strip():
                out.append(str(part["text"]).strip())
            elif part.get("type") == "tool_use":
                args = part.get("input") or {}
                detail = (
                    args.get("command")
                    or args.get("file_path")
                    or args.get("pattern")
                    or args.get("path")
                    or ""
                )
                out.append(f"> {part.get('name')} {str(detail)[:160]}".rstrip())
        return out
    if kind == "result":
        cost = event.get("total_cost_usd")
        spent = f", ${cost:.2f}" if isinstance(cost, (int, float)) else ""
        return [f"Session ended: {event.get('subtype', 'done')}{spent}"]
    return []


def _stop(proc: subprocess.Popen) -> None:
    """Stop the agent and everything it started (its own process group)."""
    if proc.poll() is not None:
        return
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


@dataclass
class Result:
    returncode: int
    published: list[Path]
    """New scenario folders, now in the repository's scenarios/."""
    skipped: list[str]
    """New folders not copied because a folder of that name already exists."""
    other_changes: list[str]
    session: Path

    @property
    def log(self) -> Path:
        return self.session / "session.log"


def run(
    agent: str,
    task: str,
    kind: str,
    *,
    model: str | None = None,
    max_cost: float | None = DEFAULT_MAX_COST,
    repo: Path = REPO_ROOT,
    readable: list[Path] | None = None,
    extra_scenarios: list[Path] | None = None,
    say: Callable[[str], None] = print,
) -> Result:
    """Run the agent in a working copy, show and log what it does, then copy new scenario folders in."""
    session = new_session(kind, repo)
    work = make_workdir(session, repo, extra_scenarios)
    scenarios_before = {p.name for p in (work / "scenarios").iterdir() if p.is_dir()}
    before = fingerprint(work)
    cmd = command(agent, task, model=model, max_cost=max_cost, last_message=session / "last-message.txt",
                  workdir=work, readable=readable)  # fmt: skip
    env = {**os.environ, SESSION_ENV: "1", "SWARMBENCH_RUNS": str(work / "runs"),
           "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"}  # fmt: skip
    (session / "task.txt").write_text(task + "\n")
    with (session / "session.log").open("x") as log, (session / "session.jsonl").open("x") as raw:
        proc = subprocess.Popen(cmd, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, stdin=subprocess.DEVNULL, start_new_session=True)  # fmt: skip
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if agent == "claude":
                    raw.write(line)
                    raw.flush()
                for text in describe_event(line) if agent == "claude" else [line.rstrip("\n")]:
                    log.write(text + "\n")
                    log.flush()
                    say(text)
            code = proc.wait()
        finally:
            _stop(proc)
    found = changes(before, fingerprint(work), scenarios_before)
    published, skipped = publish(work, found.new_folders, repo)
    return Result(code, published, skipped, found.other, session)
