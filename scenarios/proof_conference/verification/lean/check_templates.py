"""Compile problem templates or solutions with lean-check inside the scenario image.

    docker run --rm --network none --read-only --tmpfs /tmp:exec --tmpfs /home/u01:exec,uid=1001 \
        -e HOME=/home/u01 -u 1001 -v <scenario>:/scenario:ro proof-conference-test \
        python3 -I /scenario/verification/lean/check_templates.py templates /scenario/protected/conference/problems
    ... check_templates.py solutions /scenario/verification/lean/solutions [more dirs]
    ... check_templates.py time FILE [N]       compile FILE N times at once; report times and memory
    python3 check_templates.py consistency SCENARIO_DIR   (on the host; no Lean needed)

templates: every file must compile (exit 0) with exactly one warning, "declaration uses 'sorry'",
after EVOLVE-VALUE is replaced by a dummy answer. solutions: every file must compile with exit 0
and no `sorry` warning. Prints one line per file and a summary; exits 1 if anything fails.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

DUMMIES = ("default", "True", "0")
SORRY = re.compile(r"declaration uses ['`]sorry['`]")  # Lean 4.33 prints `sorry` in backticks
WORK = Path("/tmp/check")


def compile_file(path: Path) -> tuple[int, str, float]:
    start = time.monotonic()
    proc = subprocess.run(["lean-check", str(path)], capture_output=True, text=True, timeout=1800)
    return proc.returncode, proc.stdout + proc.stderr, time.monotonic() - start


def warnings(output: str) -> list[str]:
    return re.findall(r"warning: (.*)", output)


def check_template(path: Path) -> tuple[bool, str]:
    text = path.read_text()
    tries = DUMMIES if "EVOLVE-VALUE" in text else (None,)
    last = ""
    for dummy in tries:
        WORK.mkdir(exist_ok=True)
        tmp = WORK / path.name
        tmp.write_text(text if dummy is None else text.replace("EVOLVE-VALUE", dummy))
        code, out, secs = compile_file(tmp)
        warns = warnings(out)
        ok = code == 0 and len(warns) == 1 and SORRY.search(warns[0]) and "error" not in out
        note = f"{secs:5.1f}s" + (f" answer:={dummy}" if dummy else "")
        if ok:
            return True, note
        last = f"{note} exit={code} " + " | ".join(out.strip().splitlines()[:6])
    return False, last


def check_solution(path: Path) -> tuple[bool, str]:
    code, out, secs = compile_file(path)
    ok = code == 0 and not SORRY.search(out) and "error" not in out
    extra = "" if ok else " " + " | ".join(out.strip().splitlines()[:6])
    return ok, f"{secs:5.1f}s exit={code}{extra}"


def run_checks(kind: str, dirs: list[str]) -> int:
    files = sorted(f for d in dirs for f in Path(d).glob("*.lean"))
    check = check_template if kind == "templates" else check_solution
    failed = 0
    for f in files:
        ok, note = check(f)
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {f.name:45s} {note}", flush=True)
    print(f"{len(files) - failed}/{len(files)} {kind} passed")
    return 1 if failed else 0


def cgroup_peak() -> str:
    for p in ("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
        try:
            return f"{int(Path(p).read_text()) / 2**20:.0f} MiB"
        except (OSError, ValueError):
            continue
    return "n/a"


def timed(path: Path, n: int) -> int:
    """Compile `path` n times at once; print wall times, peak RSS of the largest compile and the
    container's peak memory (cgroup memory.peak, which includes the page cache)."""
    text = path.read_text().replace("EVOLVE-VALUE", "default")
    WORK.mkdir(exist_ok=True)
    copies = []
    for i in range(n):
        p = WORK / f"t{i}_{path.name}"
        p.write_text(text)
        copies.append(p)
    start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(n) as pool:
        results = list(pool.map(compile_file, copies))
    wall = time.monotonic() - start
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    for code, out, secs in results:
        print(f"exit={code} {secs:.1f}s warnings={warnings(out)}")
    print(f"{n} concurrent compile(s): wall {wall:.1f}s, max RSS of one compile {rss:.0f} MiB, "
          f"container peak {cgroup_peak()}, cpus {os.cpu_count()}")
    return 0 if all(r[0] == 0 for r in results) else 1


def consistency(scenario: Path) -> int:
    """Both problem folders hold exactly the problems in problems.json, as identical copies."""
    import json

    entries = json.loads((scenario / "protected/conference/problems.json").read_text())
    ids = {e["id"] for e in entries}
    errors = []
    if len(ids) != len(entries):
        errors.append("duplicate ids in problems.json")
    work, prot = scenario / "workspace/problems", scenario / "protected/conference/problems"
    for d in (work, prot):
        names = {f.stem for f in d.glob("*")}
        errors += [f"not in problems.json (delete it): {d / n}.lean" for n in sorted(names - ids)]
        errors += [f"missing: {d / n}.lean" for n in sorted(ids - names)]
    from_fc = scenario / "verification/lean/solutions/from_fc"
    errors += [f"solution for a problem not in problems.json (delete it): {f}"
               for f in sorted(from_fc.glob("*.lean")) if f.stem not in ids]
    for e in entries:
        a, b = work / f"{e['id']}.lean", prot / f"{e['id']}.lean"
        if a.exists() and b.exists() and a.read_bytes() != b.read_bytes():
            errors.append(f"workspace and protected copies differ: {e['id']}")
        if e["file"] != f"problems/{e['id']}.lean":
            errors.append(f"unexpected file field for {e['id']}: {e['file']}")
    for msg in errors:
        print(f"FAIL {msg}")
    print(f"{len(entries)} problems in problems.json; {'consistent' if not errors else f'{len(errors)} problem(s)'}")
    return 1 if errors else 0


def main() -> None:
    kind, args = sys.argv[1], sys.argv[2:]
    if kind == "consistency":
        sys.exit(consistency(Path(args[0])))
    if kind == "time":
        sys.exit(timed(Path(args[0]), int(args[1]) if len(args) > 1 else 1))
    sys.exit(run_checks(kind, args))


if __name__ == "__main__":
    main()
