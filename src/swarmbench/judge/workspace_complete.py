"""Completing a workspace change list the engine had to cut short.

The engine lists at most ``snapshot.MAX_CHANGES`` changes per team in the sample store, but
its start and end archives hold every file it could save. When a team's list was cut by count,
the judge compares the two archives itself (path, type, size, mode, owner and a content hash)
and adds the changes the list left out, so they join the inventory like any other. Only files
the archives themselves lack (the engine's ``notes``) stay a gap, and so does a comparison that
fails. Archives are read in memory, never extracted; their contents are untrusted.
"""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path
from typing import Any

from swarmbench.judge.extract import SampleInputs

NOTES_CAP = 50
"""The engine lists at most this many files its snapshots couldn't save (``snapshot.diff``)."""
INCOMPLETE = "workspace comparison for team {team} is incomplete (size or count caps hit)"
"""The engine-side gap (judge/extract.py) this replaces when the comparison can be completed."""


def _name(member: tarfile.TarInfo) -> str:
    """The workspace-relative name as the engine wrote it (a folder really named ``workspace`` is kept)."""
    return member.name.removeprefix("./").rstrip("/")


def archive_index(path: Path) -> dict[str, dict[str, Any]]:
    """Every entry of a snapshot archive: type, mode, uid, size, link target and content hash."""
    out: dict[str, dict[str, Any]] = {}
    with tarfile.open(path, "r:gz") as tar:
        for m in tar:
            name = _name(m)
            if not name or name == ".":
                continue
            if m.isdir():
                out[name] = {"type": "dir", "mode": m.mode, "uid": m.uid, "size": m.size}
            elif m.issym():
                out[name] = {"type": "link", "target": m.linkname, "uid": m.uid}
            elif m.isfile():
                h = hashlib.sha256()
                handle = tar.extractfile(m)
                while handle is not None and (block := handle.read(1 << 20)):
                    h.update(block)
                out[name] = {"type": "file", "mode": m.mode, "uid": m.uid, "size": m.size, "sha256": h.hexdigest()}
    return out


def _fingerprint(e: dict[str, Any]) -> tuple[Any, ...]:
    if e["type"] == "link":
        return ("link", e.get("target"))
    if e["type"] == "dir":
        return ("dir", e.get("mode"), e.get("uid"))
    return ("file", e.get("sha256"), e.get("mode"), e.get("uid"))


def recompute(start: dict[str, dict[str, Any]], end: dict[str, dict[str, Any]], agent_of: dict[int, str],
              skip: set[str]) -> list[dict[str, Any]]:
    """Every change between two archive indexes, in the engine's shape (paths under /workspace),
    leaving out ``skip`` (files the snapshots couldn't save: missing from an archive is not a change)."""
    out = []
    for path in sorted(set(start) | set(end)):
        if path in skip:
            continue
        old, new = start.get(path), end.get(path)
        if old is None:
            kind = "added"
        elif new is None:
            kind = "deleted"
        elif _fingerprint(old) != _fingerprint(new):
            kind = "changed"
        else:
            continue
        if (new or old)["type"] == "dir" and kind == "changed":
            continue  # a folder's own times change whenever its contents do
        final = new or {}
        out.append({
            "path": f"/workspace/{path}",
            "change": kind,
            "type": (new or old)["type"],
            "uid": final.get("uid"),
            "agent": agent_of.get(final.get("uid")) if final else None,
            "sha_before": (old or {}).get("sha256"),
            "sha_after": (new or {}).get("sha256"),
            "size_before": (old or {}).get("size"),
            "size_after": (new or {}).get("size"),
            "unverified": False,
            "recomputed": True,
        })
    return out


def _overflow_text(overflow: dict[str, Any]) -> str:
    folders = sorted(overflow.items(), key=lambda kv: -sum(int(kv[1].get(k) or 0)
                                                            for k in ("added", "changed", "deleted")))
    bits = []
    for folder, v in folders[:3]:
        n = sum(int(v.get(k) or 0) for k in ("added", "changed", "deleted"))
        who = ", ".join(v.get("agents") or []) or "unknown owners"
        bits.append(f"{n} in {folder} ({who})")
    return "; ".join(bits)


def complete_workspace(inputs: SampleInputs, run_root: Path | None) -> list[str]:
    """Fill in the changes the engine's list left out, from the archives. Adjusts
    ``inputs.workspace_changes`` and ``inputs.workspace_gaps``; returns plain technical notes."""
    notes: list[str] = []
    agent_of = {int(a["uid"]): str(a["name"]) for a in inputs.agents_meta if a.get("uid") is not None
                and a.get("name")}
    for team, info in inputs.workspace_teams.items():
        if not info.get("truncated"):
            continue
        generic = INCOMPLETE.format(team=team)
        gaps = [g for g in inputs.workspace_gaps if g != generic]
        missing_files = info.get("notes") or []
        cut_by_count = info.get("total", 0) > info.get("listed", 0)
        new_gaps: list[str] = []
        # the notes say which files the snapshots couldn't save; capped at 50, or marking an entry limit,
        # they don't say all of them, and a file missing from one archive can't be told from a real change
        notes_complete = len(missing_files) < NOTES_CAP and not any(n.startswith("(") for n in missing_files)
        if cut_by_count and not notes_complete:
            new_gaps.append(f"workspace comparison for team {team} is incomplete: the engine listed "
                            f"{info['listed']:,} of {info['total']:,} changes, and the snapshots themselves are "
                            "incomplete, so the rest can't be worked out from them")
            cut_by_count = False
        elif cut_by_count:
            folder = run_root / "workspace" / team if run_root is not None else None
            try:
                if folder is None or not (folder / "start.tar.gz").exists() or not (folder / "end.tar.gz").exists():
                    raise FileNotFoundError("the snapshots are missing")
                found = recompute(archive_index(folder / "start.tar.gz"), archive_index(folder / "end.tar.gz"),
                                  agent_of, set(missing_files))
            except Exception as exc:  # unreadable or missing archives: still a gap
                where = _overflow_text(info.get("overflow") or {})
                new_gaps.append(
                    f"workspace comparison for team {team} is incomplete: the engine listed {info['listed']:,} of "
                    f"{info['total']:,} changes, and comparing the rest from the snapshots failed "
                    f"({type(exc).__name__}: {str(exc)[:120]})" + (f"; the rest are {where}" if where else ""))
            else:
                listed = {c["path"] for c in inputs.workspace_changes if c.get("team") == team}
                extra = [{**c, "team": team, "owner_uid": c.get("uid")} for c in found if c["path"] not in listed]
                inputs.workspace_changes += extra
                notes.append(f"The engine listed {info['listed']:,} of {info['total']:,} changed files for team "
                             f"{team}; the judge compared the other {len(extra):,} from the start and end "
                             "snapshots.")
        if missing_files:
            shown = ", ".join(missing_files[:5]) + (", ..." if len(missing_files) > 5 else "")
            new_gaps.append(f"{len(missing_files)} file(s) in team {team} could not be saved in the snapshots (too "
                            f"big, or past a limit), so their changes were not compared: {shown}")
        if not cut_by_count and not missing_files:
            new_gaps.append(generic)  # truncated, but nothing says why: keep the engine's word for it
        inputs.workspace_gaps = gaps + new_gaps
    return notes
