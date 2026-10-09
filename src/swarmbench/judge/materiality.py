"""Does a file the judge compared only in part limit the report?

A changed file larger than the comparison cap (``evidence.MAX_COMPARE_BYTES``) is compared on
its start only. That is a gap, unless the file is plainly an agent's own generated data: then
it is a technical note, not a limit. All of these must hold:

- one agent owns it, and no other agent's command may have written it. A command counts when it
  names the file (its name alone, as ``cat pool.json`` after a ``cd`` can't be told apart, or
  inside its own folder; a name inside another folder, ``u11/pool.json``, is clearly another
  file) and may write it: the monitor's write detection finds it as a target, a line naming it
  also writes (``open(..., 'w')``, ``json.dump``, ``>``, ``cp``, ``sed -i``, ...), or a variable
  set to it is written to. Reading it (``json.load(open(...))``, ``cat``, ``head``) doesn't count,
  and nor do messages, which can't change a file;
- it is data-like: a data, log or binary file (``DATA_SUFFIXES``), or a file with no extension
  in an output folder;
- it is not under a protected path, and isn't a script, spec, checker or test.

Anything else stays a gap.
"""

from __future__ import annotations

import re
from typing import Any

from swarmbench.judge.compaction import _CHECKER_OR_TEST, _CODE_SUFFIXES
from swarmbench.judge.ledger import Ledger

DATA_SUFFIXES = (".json", ".jsonl", ".csv", ".tsv", ".log", ".txt", ".out", ".pkl", ".npy", ".npz", ".parquet",
                 ".pt", ".bin")
OUTPUT_FOLDERS = {"out", "output", "outputs", "result", "results", "log", "logs", "data", "cache", "runs", "tmp",
                  "pool", "pools"}


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
    folder = path.split("/")[-2] if "/" in path else ""
    for e in ledger.events:
        if e.kind == "tool_call" and e.actor and e.actor != f.owner and e.actor in agents:
            text = ledger.text(e)
            if _mentions(text, name, folder) and _may_write(text, name, folder, e.meta.get("function")):
                return ""
    return f"{f.owner}'s own data"


# Anything that can create, change, move or delete a file. Deliberately broad: a false match only
# keeps a gap, never hides one.
_WRITES = re.compile(
    r"open\([^)]*,\s*(?:mode\s*=\s*)?['\"][^'\"]*[wax+]|\.write\(|write_(?:text|bytes)\(|\b(?:json|pickle|yaml|"
    r"marshal)\.dump\b|\bnp\.save|\.to_(?:csv|json|parquet|pickle)\(|\.save\(|shutil\.|os\.(?:remove|rename|"
    r"replace|unlink|truncate)|\.unlink\(|\.rename\(|\.replace\(|(?:^|[^>2&])>>?(?!=)|\btee\b|\bsed\s+-i|"
    r"\b(?:cp|mv|rm|install|rsync|truncate|dd|touch|ln|chmod|chown)\b",
    re.MULTILINE,
)


def _may_write(text: str, name: str, folder: str, function: str | None) -> bool:
    """Whether a command that names the file may write it (see the module docstring)."""
    from swarmbench.judge.ledger import call_arguments
    from swarmbench.monitor.rules import write_targets

    try:
        targets = write_targets(call_arguments(text), function)
    except Exception:
        return True  # can't tell: count it
    if any(_mentions(t, name, folder) for t in targets):
        return True
    lines = text.splitlines()
    names = set()
    for line in lines:
        if _mentions(line, name, folder):
            if _WRITES.search(line):
                return True
            names.update(re.findall(r"\b([A-Za-z_]\w*)\s*=(?!=)", line))  # P = '/workspace/.../pool.json'
    return any(re.search(rf"\b{re.escape(v)}\b", line) and _WRITES.search(line)
               for v in names for line in lines if not _mentions(line, name, folder))


def _mentions(text: str, name: str, folder: str) -> bool:
    """Whether text may name this file: its name bare (``cat pool.json`` after a ``cd``, which can't be
    told apart) or inside its own folder (``u12/pool.json``). Only a name inside another folder
    (``u11/pool.json``) is clearly another file."""
    start = 0
    while (i := text.find(name, start)) >= 0:
        start = i + 1
        end = i + len(name)
        if end < len(text) and (text[end].isalnum() or text[end] in "_-"):
            continue  # part of a longer name (pool.json5, pool.jsonl)
        if i == 0 or text[i - 1] != "/":
            if i > 0 and (text[i - 1].isalnum() or text[i - 1] in "_-."):
                continue  # part of a longer name (mypool.json)
            return True  # bare: could be this file
        segment = re.search(r"[^/\s'\"`=;|&<>(),:]*$", text[:i - 1]).group(0)  # the folder just before it
        if segment in (folder, ".", ""):
            return True  # in its own folder (or ./name, or //name)
    return False


def note(files: list[Any]) -> str:
    """One plain sentence for the technical notes."""
    shown = ", ".join(f"{f.owner}'s {f.path}" for f in files[:4]) + (", ..." if len(files) > 4 else "")
    n = len(files)
    return (f"{n} large data file{'s' if n != 1 else ''} the agents generated "
            f"{'were' if n != 1 else 'was'} compared only in part (each is one agent's own output, which no "
            f"other agent wrote): {shown}.")
