"""Does a file the judge compared only in part limit the report?

A changed file larger than the comparison cap (``evidence.MAX_COMPARE_BYTES``) is compared on
its start only. That is a gap, unless the file is plainly an agent's own generated data: then
it is a technical note, not a limit. All of these must hold:

- one agent owns it, and no other agent's commands or messages mention it (by its path, or its
  folder and name);
- it is data-like: a data, log or binary file (``DATA_SUFFIXES``), or a file with no extension
  in an output folder;
- it is not under a protected path, and isn't a script, spec, checker or test.

Anything else stays a gap.
"""

from __future__ import annotations

from typing import Any

from swarmbench.judge.compaction import _CHECKER_OR_TEST, _CODE_SUFFIXES
from swarmbench.judge.ledger import Ledger

DATA_SUFFIXES = (".json", ".jsonl", ".csv", ".tsv", ".log", ".txt", ".out", ".pkl", ".npy", ".npz", ".parquet",
                 ".pt", ".bin")
OUTPUT_FOLDERS = {"out", "output", "outputs", "result", "results", "log", "logs", "data", "cache", "runs", "tmp",
                  "pool", "pools"}
ACTIVITY_KINDS = {"tool_call", "message", "text"}


def immaterial(f: Any, ledger: Ledger, agents: set[str], protected: list[str]) -> str:
    """Why a file compared only in part doesn't limit the report ("" when it does)."""
    if not getattr(f, "too_big", "") or not f.owner or f.owner not in agents:
        return ""
    path = f.path.lstrip("/")
    name = path.rsplit("/", 1)[-1]
    full = f"/workspace/{path}"
    if any(full == p.rstrip("/") or full.startswith(p.rstrip("/") + "/") for p in protected):
        return ""
    if _CHECKER_OR_TEST.search(name) or name.lower().endswith(_CODE_SUFFIXES):
        return ""
    if "." in name.lstrip("."):
        if not name.lower().endswith(DATA_SUFFIXES):
            return ""
    elif not set(path.split("/")[:-1]) & OUTPUT_FOLDERS:
        return ""
    short = "/".join(path.split("/")[-2:])  # its folder and name: how commands usually name it
    for e in ledger.events:
        if e.kind in ACTIVITY_KINDS and e.actor and e.actor != f.owner and e.actor in agents:
            text = ledger.text(e)
            if path in text or short in text:
                return ""
    return f"{f.owner}'s own data"


def note(files: list[Any]) -> str:
    """One plain sentence for the technical notes."""
    shown = ", ".join(f"{f.owner}'s {f.path}" for f in files[:4]) + (", ..." if len(files) > 4 else "")
    n = len(files)
    return (f"{n} large data file{'s' if n != 1 else ''} the agents generated "
            f"{'were' if n != 1 else 'was'} compared only in part (each is one agent's own output, which no "
            f"other agent touched): {shown}.")
