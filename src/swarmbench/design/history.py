"""Optional backdated git history for a scenario's workspace.

A real ``.git`` folder can't be stored inside the swarmbench repository (git
would record it as an embedded repository with no content), so a scenario
describes its history in ``history.yaml`` at the scenario root. Agents never
see that file, only the repository built from it when the run starts::

    repo: rfcodes                  # optional subfolder of the workspace that becomes the repo
    workspace: workspace           # optional; which workspace folder this belongs to
    timezone: Europe/Berlin        # optional, default UTC
    default_branch: main           # optional, default main
    commits:                       # oldest first
      - id: c01                    # optional label
        date: "-41d 10:12"         # days before the run starts, local time
        author: "Ruth Okafor <rokafor@halden-labs.com>"
        message: initial import of frame parser
        files:                     # repo-relative path -> scenario-relative source, or null to delete
          src/parser.py: history/c01/parser.py
          README.md: workspace/rfcodes/README.md
      - date: "-12d 16:40"
        author: "Tomas Lindqvist <tlindqvist@halden-labs.com>"
        branch: tl/fast-path       # a new name starts a branch from the head of `from`
        from: main                 # optional, default the default branch
        message: wip
        files: {src/parser.py: history/c02/parser.py}
      - date: "-3d 09:05"
        author: "Ruth Okafor <rokafor@halden-labs.com>"
        merge: tl/fast-path        # optional: a merge commit of that branch into this commit's branch
        message: Merge branch 'tl/fast-path'

Rules: files never mentioned in any commit are added in the first commit;
after replaying, the default branch must equal ``workspace/<repo>/`` exactly
(``check_history`` checks this without running git); the default branch ends
checked out. Dates get a few minutes of seeded jitter and always end before
the run start. File modification times are set to the last commit that
changed each file.

Replay is deterministic: the full tree of every commit is computed first (a
merge takes the other branch's version of each file it changed since it
forked), then git records exactly those trees.
"""

from __future__ import annotations

import os
import random
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from swarmbench.design.dates import render_dates
from swarmbench.design.folder import UnsafePath, path_clash, safe_path

HISTORY_FILE = "history.yaml"
_AUTHOR = re.compile(r"^\s*([^<>]+?)\s*<([^<>@\s]+@[^<>\s]+)>\s*$")
_DATE = re.compile(r"^-(\d+)d\s+([01]?\d|2[0-3]):([0-5]\d)$")

Tree = dict[str, bytes]


@dataclass
class _Commit:
    days: int
    hour: int
    minute: int
    author: str
    email: str
    message: str
    branch: str
    merge: str | None
    tree: Tree
    changed: set[str] = field(default_factory=set)
    """Paths whose content changed on this branch in this commit."""


@dataclass
class _Plan:
    repo_prefix: str
    """Scenario-relative folder of the repository, ending in '/'."""
    timezone: str
    default_branch: str
    commits: list[_Commit]
    forks: dict[str, str]
    """branch -> the branch it was started from."""


def check_history(text: str, files: Mapping[str, str | bytes]) -> list[str]:
    """Problems with a history.yaml, given every file in the scenario folder (path -> content)."""
    try:
        _plan(text, files)
    except _HistoryError as e:
        return e.errors
    return []


def history_workspace(scenario_dir: Path) -> str | None:
    """Which workspace folder the scenario's history belongs to (None: no history)."""
    path = scenario_dir / HISTORY_FILE
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text()) or {}
    return str(data.get("workspace", "workspace")).strip("/")


def seed_workspace(
    scenario_dir: Path,
    workspace: str,
    dest: Path,
    now: datetime | None = None,
    seed: int | str | None = None,
) -> bool:
    """Fill the empty folder ``dest`` with the scenario's ``workspace`` folder and its git history.

    ``now`` is the run start (default: now); ``seed`` makes the time jitter
    repeatable. File times are backdated even without a history. Returns True
    when a git repository was built.
    """
    source_dir = scenario_dir / workspace
    final: Tree = {
        p.relative_to(source_dir).as_posix(): p.read_bytes()
        for p in sorted(source_dir.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty")

    plan = None
    if history_workspace(scenario_dir) == workspace.strip("/"):
        files = {
            p.relative_to(scenario_dir).as_posix(): p.read_bytes()
            for p in scenario_dir.rglob("*")
            if p.is_file() and not p.is_symlink()
        }
        plan = _plan((scenario_dir / HISTORY_FILE).read_text(), files)
    tz = ZoneInfo(plan.timezone if plan else "UTC")
    now = (now or datetime.now(tz)).astimezone(tz)
    rng = random.Random(seed)

    def render(content: bytes) -> bytes:
        try:
            return render_dates(content.decode("utf-8"), now).encode("utf-8")
        except UnicodeDecodeError:
            return content

    for rel, content in final.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_bytes(render(content))
    if plan is None:
        for rel in final:
            _touch(dest / rel, now - timedelta(days=rng.uniform(1, 30)))
        return False

    repo_rel = plan.repo_prefix[len(workspace.strip("/")) + 1 :]
    repo_dir = dest / repo_rel if repo_rel else dest
    times = _replay(plan, repo_dir, now, rng, render)
    # Files outside the repository: edited at some point during the history.
    first, last = times[0], times[-1]
    for rel in final:
        inside = rel.startswith(repo_rel) if repo_rel else True
        if not inside:
            _touch(dest / rel, first + (last - first) * rng.random())
    return True


# --- planning (pure Python, no git) ---------------------------------------------------


class _HistoryError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _plan(text: str, files: Mapping[str, str | bytes]) -> _Plan:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise _HistoryError([f"{HISTORY_FILE} is not valid YAML: {e}"]) from None
    if not isinstance(data, dict) or not isinstance(data.get("commits"), list) or not data["commits"]:
        raise _HistoryError([f"{HISTORY_FILE} needs a non-empty 'commits' list"])
    blobs = {p: c.encode() if isinstance(c, str) else c for p, c in files.items()}
    errors: list[str] = []
    timezone = str(data.get("timezone", "UTC"))
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        errors.append(f"{HISTORY_FILE}: unknown timezone {timezone!r}")
    try:
        workspace = safe_path(str(data.get("workspace", "workspace")).strip("/"))
        repo = str(data.get("repo") or "").strip("/")
        prefix = f"{workspace}/{safe_path(repo)}/" if repo else f"{workspace}/"
    except UnsafePath as e:
        raise _HistoryError([f"{HISTORY_FILE}: workspace/repo: {e}"]) from None
    final = {p[len(prefix) :]: c for p, c in blobs.items() if p.startswith(prefix)}
    if not final:
        errors.append(f"{HISTORY_FILE}: {prefix} has no files")
    default = str(data.get("default_branch", "main"))
    if not _valid_branch(default):
        errors.append(f"{HISTORY_FILE}: bad default_branch {default!r}")

    mentioned = {
        str(path).strip("/")
        for c in data["commits"]
        if isinstance(c, dict) and isinstance(c.get("files"), dict)
        for path in c["files"]
    }
    trees: list[Tree] = []
    parents: list[list[int]] = []
    heads: dict[str, int] = {}
    forks: dict[str, str] = {}
    commits: list[_Commit] = []
    previous_days: int | None = None
    for i, raw in enumerate(data["commits"], 1):
        where = f"{HISTORY_FILE} commit {raw.get('id', i) if isinstance(raw, dict) else i}"
        if not isinstance(raw, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        author = _AUTHOR.match(str(raw.get("author", "")))
        if not author:
            errors.append(f"{where}: author must look like 'Name <email>'")
        date = _DATE.match(str(raw.get("date", "")).strip())
        if not date:
            errors.append(f'{where}: date must look like "-41d 10:12" (days before the run, local time)')
        elif previous_days is not None and int(date.group(1)) > previous_days:
            errors.append(f"{where}: commits must be oldest first")
        else:
            previous_days = int(date.group(1))
        message = str(raw.get("message", "")).strip()
        if not message:
            errors.append(f"{where}: message is empty")
        branch = str(raw.get("branch", default))
        if not _valid_branch(branch):
            errors.append(f"{where}: {branch!r} is not a valid git branch name")
        if not heads and branch != default:
            errors.append(f"{where}: the first commit must be on {default}")

        if branch in heads:
            parent: int | None = heads[branch]
        elif not heads:
            parent = None
        else:
            origin = str(raw.get("from", default))
            if origin not in heads:
                errors.append(f"{where}: 'from' names unknown branch {origin!r}")
                continue
            parent = heads[origin]
            forks[branch] = origin
        if parent is None:
            tree = {p: c for p, c in final.items() if p not in mentioned}
        else:
            tree = dict(trees[parent])
        before = dict(tree) if branch in heads else {}
        commit_parents = [] if parent is None else [parent]

        merge = raw.get("merge")
        if merge is not None:
            merge = str(merge)
            if merge not in heads or merge == branch:
                errors.append(f"{where}: merge must name an earlier, different branch")
                merge = None
            else:
                other = heads[merge]
                base = _merge_base(parents, parent, other)
                base_tree = trees[base] if base is not None else {}
                theirs = trees[other]
                for path in set(base_tree) | set(theirs):
                    if theirs.get(path) != base_tree.get(path):
                        if path in theirs:
                            tree[path] = theirs[path]
                        else:
                            tree.pop(path, None)
                commit_parents.append(other)

        sources = raw.get("files") or {}
        if not isinstance(sources, dict):
            errors.append(f"{where}: 'files' must map repo paths to a source file or null")
            sources = {}
        for raw_path, source in sources.items():
            try:
                path = safe_path(str(raw_path).strip("/"))
            except UnsafePath as e:
                errors.append(f"{where}: {e}")
                continue
            if source is None:
                tree.pop(path, None)
            elif str(source) in blobs:
                tree[path] = blobs[str(source)]
            else:
                errors.append(f"{where}: source {source} for {path} does not exist in the scenario folder")
        clash = path_clash(tree)
        if clash:
            errors.append(f"{where}: {clash} is both a file and a folder")

        changed = {p for p in set(tree) | set(before) if tree.get(p) != before.get(p)}
        trees.append(tree)
        parents.append(commit_parents)
        heads[branch] = len(trees) - 1
        if author and date:
            commits.append(
                _Commit(
                    days=int(date.group(1)),
                    hour=int(date.group(2)),
                    minute=int(date.group(3)),
                    author=author.group(1),
                    email=author.group(2),
                    message=message,
                    branch=branch,
                    merge=merge,
                    tree=dict(tree),
                    changed=changed,
                )
            )

    names = sorted(set(heads) | {default})
    for a in names:
        for b in names:
            if b.startswith(a + "/"):
                errors.append(f"{HISTORY_FILE}: branches {a!r} and {b!r} can't both exist in git")
    if not errors:
        end = trees[heads[default]] if default in heads else {}
        diffs = sorted(
            [f"{p} differs" for p in set(end) & set(final) if end[p] != final[p]]
            + [f"{p} is in workspace but not on {default}" for p in set(final) - set(end)]
            + [f"{p} is on {default} but not in workspace" for p in set(end) - set(final)]
        )
        if diffs:
            shown = "; ".join(diffs[:8]) + (f"; and {len(diffs) - 8} more" if len(diffs) > 8 else "")
            errors.append(
                f"{HISTORY_FILE}: after the last commit, {default} must equal {prefix} exactly: {shown}"
            )
    if errors:
        raise _HistoryError(errors)
    return _Plan(prefix, timezone, default, commits, forks)


def _merge_base(parents: list[list[int]], a: int | None, b: int) -> int | None:
    """The latest commit that is an ancestor of both ``a`` and ``b``."""
    if a is None:
        return None

    def ancestors(start: int) -> set[int]:
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack += parents[node]
        return seen

    common = ancestors(a) & ancestors(b)
    return max(common) if common else None


def _valid_branch(name: str) -> bool:
    """Git's branch-name rules (git check-ref-format --branch), without running git."""
    if not name or name in ("HEAD", "@") or name.startswith(("-", "/")) or name.endswith(("/", ".")):
        return False
    if any(bad in name for bad in ("..", "//", "@{", "\\")) or re.search(r"[\x00-\x20\x7f~^:?*\[]", name):
        return False
    return all(part and not part.startswith(".") and not part.endswith(".lock") for part in name.split("/"))


# --- replay with git ------------------------------------------------------------------


def _replay(
    plan: _Plan, repo_dir: Path, now: datetime, rng: random.Random, render: Callable[[bytes], bytes]
) -> list[datetime]:
    """Record the planned trees with git. Returns each commit's time."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    final = {p.relative_to(repo_dir).as_posix(): p.read_bytes() for p in repo_dir.rglob("*") if p.is_file()}
    _git(repo_dir, {}, "init", "-q", "-b", plan.default_branch)
    current = plan.default_branch
    known = {plan.default_branch}
    times = _commit_times(plan.commits, now, rng)
    last_changed: dict[str, datetime] = {}
    for commit, when in zip(plan.commits, times, strict=True):
        if commit.branch != current:
            if commit.branch in known:
                _git(repo_dir, {}, "checkout", "-q", "-f", commit.branch)
            else:
                origin = plan.forks[commit.branch]
                _git(repo_dir, {}, "checkout", "-q", "-f", "-b", commit.branch, origin)
                known.add(commit.branch)
            current = commit.branch
        if commit.merge:
            _git(repo_dir, {}, "merge", "-q", "--no-ff", "--no-commit", "-s", "ours", commit.merge)
        _write_tree(repo_dir, {p: render(c) for p, c in commit.tree.items()})
        _git(repo_dir, {}, "add", "-A", "-f", ".")
        _commit(repo_dir, commit, when)
        if commit.branch == plan.default_branch:
            for path in commit.changed:
                last_changed[path] = when
    if current != plan.default_branch:
        _git(repo_dir, {}, "checkout", "-q", "-f", plan.default_branch)
    _write_tree(repo_dir, final)
    for rel in final:
        _touch(repo_dir / rel, last_changed.get(rel, times[0]))
    return times


def _write_tree(repo_dir: Path, tree: Tree) -> None:
    for path in sorted(repo_dir.rglob("*"), reverse=True):
        rel = path.relative_to(repo_dir)
        if rel.parts[0] == ".git":
            continue
        if path.is_file() or path.is_symlink():
            if rel.as_posix() not in tree:
                path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    root = repo_dir.resolve()
    for rel, content in tree.items():
        target = repo_dir / rel
        if not target.resolve().is_relative_to(root) or ".git" in Path(rel).parts:
            raise ValueError(f"history path {rel!r} leaves the repository")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != content:
            target.write_bytes(content)


def _commit_times(commits: list[_Commit], now: datetime, rng: random.Random) -> list[datetime]:
    """Each commit's time: as written plus jitter, strictly increasing, all before the run starts."""
    times: list[datetime] = []
    for commit in commits:
        day = (now - timedelta(days=commit.days)).date()
        when = datetime(day.year, day.month, day.day, commit.hour, commit.minute, tzinfo=now.tzinfo)
        when += timedelta(minutes=rng.randint(-7, 7), seconds=rng.randint(0, 59))
        if times and when <= times[-1]:
            when = times[-1] + timedelta(minutes=rng.randint(2, 15))
        times.append(when)
    cap = now - timedelta(minutes=20)
    if times and times[-1] > cap:
        shift = times[-1] - cap
        times = [t - shift for t in times]
    return times


def _commit(repo_dir: Path, commit: _Commit, when: datetime) -> None:
    stamp = when.isoformat()
    env = {
        "GIT_AUTHOR_NAME": commit.author,
        "GIT_AUTHOR_EMAIL": commit.email,
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_NAME": commit.author,
        "GIT_COMMITTER_EMAIL": commit.email,
        "GIT_COMMITTER_DATE": stamp,
    }
    _git(repo_dir, env, "commit", "-q", "--allow-empty", "-m", commit.message)


def _git(cwd: Path, extra_env: dict[str, str], *args: str) -> None:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "ops",
        "GIT_AUTHOR_EMAIL": "ops@localhost",
        "GIT_COMMITTER_NAME": "ops",
        "GIT_COMMITTER_EMAIL": "ops@localhost",
        **extra_env,
    }
    cmd = ["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={os.devnull}", *args]
    subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True)


def _touch(path: Path, when: datetime) -> None:
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))
