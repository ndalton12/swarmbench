"""Problem templates for proof_conference, generated from a Formal Conjectures checkout.

    python make_problems.py survey FC_DIR > survey.tsv
        one line per unproved theorem in FC: file, name, category, AMS, answer, length

    python make_problems.py generate FC_DIR [--selection selection.yaml] [--out SCENARIO_DIR]
        writes workspace/problems/<ID>.lean, protected/conference/problems/<ID>.lean and
        protected/conference/problems.json for the problems listed in selection.yaml

FC_DIR must be checked out at the commit named in selection.yaml (`fc_commit`).

A template is the FC file cut down to one theorem: everything before the theorem that it may
depend on (imports, namespaces, opens, definitions, proved lemmas), then an empty editable
region for helpers, the theorem with its proof replaced by an editable region holding `sorry`,
and the `end` lines that close the namespaces. Unproved theorems other than the chosen one are
dropped, as is everything after the theorem. `answer(sorry)` becomes `answer(EVOLVE-VALUE)`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SCENARIO = HERE.parents[1]

BEGIN = "-- EDITABLE BEGIN"
END = "-- EDITABLE END"
PLACEHOLDER = "EVOLVE-VALUE"
# Words the conference checker rejects anywhere outside comments (kept in step with its blacklist).
BLACKLIST = ("axiom", "sorry", "macro", "syntax", "elab", "native_decide", "#exit")
PERSONAS = ("algebra", "analysis", "combinatorics", "number_theory")


def strip_comments(text: str) -> str:
    """Text with `--` line comments and (nested) `/- -/` block comments blanked, strings kept."""
    out = []
    i, depth, n = 0, 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if depth == 0 and in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
        elif depth == 0 and c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif text.startswith("/-", i):
            depth += 1
            out.append("  ")
            i += 2
        elif depth > 0 and text.startswith("-/", i):
            depth -= 1
            out.append("  ")
            i += 2
        elif depth > 0:
            out.append("\n" if c == "\n" else " ")
            i += 1
        elif text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def blacklisted(code_text: str) -> list[str]:
    code = strip_comments(code_text)
    found = []
    for w in BLACKLIST:
        pattern = re.escape(w) if w.startswith("#") else rf"(?<![\w.']){re.escape(w)}(?![\w'])"
        if re.search(pattern, code):
            found.append(w)
    return found


@dataclass
class Item:
    """A top-level chunk of a Lean file: a declaration with its docstring and attributes, a
    command (open, namespace, end, ...), or a standalone comment."""

    text: str
    code: str = ""
    kind: str = ""  # decl keyword, or "namespace", "section", "end", "open", "comment", "other"
    name: str = ""
    attrs: str = ""

    def __post_init__(self) -> None:
        self.code = strip_comments(self.text)
        body = self.code.strip()
        if not body:
            self.kind = "comment"
            return
        attrs = []
        while True:  # attributes and `open X in` / `set_option x v in` prefixes, in any order
            if body.startswith("@["):
                depth, j = 0, 0
                for j, ch in enumerate(body):
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            break
                attrs.append(body[: j + 1])
                body = body[j + 1:].strip()
            elif re.match(r"^(open|set_option)\b[^\n]*\bin\b", body):
                body = re.sub(r"^(open|set_option)\b.*?\bin\b\s*", "", body, count=1, flags=re.S)
            else:
                break
        self.attrs = " ".join(attrs)
        words = body.split()
        modifiers = {"noncomputable", "private", "protected", "public", "nonrec", "partial", "unsafe", "@[expose]"}
        k = 0
        while k < len(words) and words[k] in modifiers:
            k += 1
        first = words[k] if k < len(words) else ""
        if first in ("theorem", "lemma", "def", "abbrev", "instance", "structure", "inductive", "class",
                     "example", "opaque", "irreducible_def"):
            self.kind = first
            self.name = words[k + 1] if k + 1 < len(words) and first != "example" else ""
        elif first in ("namespace", "section", "end", "open", "variable", "universe", "module",
                       "import", "set_option", "attribute", "notation", "local", "scoped",
                       "export", "omit", "include", "deriving"):
            self.kind = first
            self.name = words[k + 1] if k + 1 < len(words) else ""
        elif words and words[0] == "public" and len(words) > 1 and words[1] == "import":
            self.kind = "import"
        else:
            self.kind = "other"

    @property
    def unproved(self) -> bool:
        return bool(re.search(r"(?<![\w.'])sorry(?![\w'])", self.code))

    @property
    def category(self) -> str:
        m = re.search(r"category\s+([a-zA-Z]+(?:\s+(?:open|solved))?)", self.attrs)
        return m.group(1) if m else ""

    @property
    def ams(self) -> list[int]:
        m = re.search(r"AMS((?:\s+\d+)+)", self.attrs)
        return [int(x) for x in m.group(1).split()] if m else []


def split_items(text: str) -> list[Item]:
    """Split a file into top-level items. A new item starts at a non-blank line in column 0 that
    is outside any block comment and any open bracket (an attribute may continue in column 0);
    docstrings, attributes and `... in` lines join the next item."""
    lines = text.splitlines(keepends=True)
    code_lines = strip_comments(text).splitlines(keepends=True)
    starts = []
    depth = 0
    brackets = 0
    for idx, line in enumerate(lines):
        if depth == 0 and brackets == 0 and line.strip() and not line[0].isspace():
            starts.append(idx)
        # update block-comment depth using the raw line (strings with /- are rare in FC)
        depth += len(re.findall(r"/-", line)) - len(re.findall(r"-/", line))
        depth = max(depth, 0)
        code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code_lines[idx] if idx < len(code_lines) else "")
        brackets = max(brackets + code.count("[") + code.count("(") - code.count("]") - code.count(")"), 0)
    chunks = []
    for a, b in zip(starts, starts[1:] + [len(lines)]):
        chunks.append("".join(lines[a:b]))
    prefix_lead = "".join(lines[: starts[0]]) if starts else text
    items: list[Item] = []
    pending = prefix_lead
    for chunk in chunks:
        joined = pending + chunk
        stripped = chunk.lstrip()
        is_prefix = (
            stripped.startswith("/--")
            or (stripped.startswith("@[") and Item(chunk).kind == "comment")
            or bool(re.match(r"^(open|set_option)\b[^\n]*\bin\s*$", strip_comments(chunk).strip()))
        )
        if stripped.startswith("@[") and not is_prefix:
            is_prefix = Item(chunk).kind == "other" and strip_comments(chunk).strip().endswith("]")
        if is_prefix:
            pending = joined
            continue
        items.append(Item(joined))
        pending = ""
    if pending:
        items.append(Item(pending))
    return items


def theorems(path: Path) -> list[Item]:
    return [it for it in split_items(path.read_text()) if it.kind in ("theorem", "lemma")]


def survey(fc: Path) -> None:
    print("file\tname\tcategory\tams\tanswer\tchars\tstatement")
    for path in sorted((fc / "FormalConjectures").rglob("*.lean")):
        rel = path.relative_to(fc)
        for it in theorems(path):
            if not it.unproved:
                continue
            statement = re.sub(r"\s+", " ", it.code.split(":= by")[0].split("theorem", 1)[-1]).strip()
            print(f"{rel}\t{it.name}\t{it.category}\t{' '.join(map(str, it.ams))}\t"
                  f"{'answer(sorry)' in it.code}\t{len(statement)}\t{statement[:160]}")


def answer_span(text: str) -> tuple[int, int] | None:
    """Start and end of the term inside the first `answer( ... )`, matching parentheses."""
    i = text.find("answer(")
    if i < 0:
        return None
    start = i + len("answer(")
    depth = 1
    for j in range(start, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return start, j
    raise ValueError("unbalanced answer(")


def make_template(path: Path, theorem: str, strip_proof: bool = False) -> tuple[str, Item, str | None]:
    items = split_items(path.read_text())
    idx = [i for i, it in enumerate(items) if it.kind in ("theorem", "lemma") and it.name == theorem]
    if len(idx) != 1:
        raise SystemExit(f"{path}: expected one theorem named {theorem}, found {len(idx)}")
    k = idx[0]
    target = items[k]
    out: list[str] = []
    stack: list[tuple[str, str]] = []  # open scopes: (kind, name)
    dropped: list[str] = []
    for it in items[:k]:
        uses_dropped = any(re.search(rf"(?<![\w']){re.escape(d)}(?![\w.'])", it.code) for d in dropped)
        # unproved results are dropped; so are proved ones that would trip the checker's
        # blacklist, add a second `answer(` (the checker reads the first one) or use a dropped one
        if it.kind in ("theorem", "lemma", "example") and (
            it.unproved or blacklisted(it.text) or "answer(" in it.text or uses_dropped
        ):
            if it.name:
                dropped.append(it.name)
            continue
        if it.kind in ("def", "abbrev", "instance", "structure", "inductive", "class", "opaque") and (
            it.unproved or blacklisted(it.text) or uses_dropped
        ):
            raise SystemExit(f"{path}: {it.kind} {it.name} before {theorem} uses a blacklisted word "
                             "or an unproved result")
        if it.kind in ("namespace", "section"):
            stack.append((it.kind, it.name if it.kind == "namespace" else _section_name(it)))
        elif it.kind == "end":
            if stack:
                stack.pop()
        out.append(it.text)
    head = "".join(out).rstrip("\n") + "\n"
    statement, proof = _split_proof(target.text, strip_proof)
    if proof.strip() != "sorry" and not strip_proof:
        raise SystemExit(f"{path}: {theorem} is not a bare `sorry` proof")
    known = None  # FC's answer when the problem is solved, e.g. `True`
    if span := answer_span(statement):
        a, b = span
        known = None if statement[a:b].strip() == "sorry" else statement[a:b].strip()
        statement = statement[:a] + PLACEHOLDER + statement[b:]
    body = f"{statement}:= by\n  {BEGIN}\n  sorry\n  {END}\n"
    tail = []
    for kind, name in reversed(stack):
        if kind == "namespace":
            tail.append(f"end {name}\n")
        elif kind == "section" and name is not None:
            tail.append(f"end {name}\n".replace("end \n", "end\n"))
    text = head + f"\n{BEGIN}\n{END}\n\n" + body + ("\n" + "".join(tail) if tail else "")
    return text, target, known


def _section_name(it: Item) -> str | None:
    """Name of a section, "" for an anonymous one, None for the file-wide public section
    (FC opens `@[expose] public section` without closing it)."""
    words = it.code.split()
    if "public" in words and words[-1] == "section":
        return None
    i = words.index("section")
    return words[i + 1] if i + 1 < len(words) else ""


def _split_proof(text: str, strip_proof: bool = False) -> tuple[str, str]:
    """(the declaration up to its proof's `:=`, the proof). With strip_proof, the proof starts at
    the first `:= by` outside brackets (for theorems FC has already proved)."""
    m = re.search(r":=\s*(?:by\s+)?(sorry)\s*$", text.rstrip())
    if m:
        return text[: m.start()].rstrip() + " ", m.group(1)
    if strip_proof:
        code = strip_comments(text)
        depth = 0
        for i, ch in enumerate(code):
            if ch in "([{⟨":
                depth += 1
            elif ch in ")]}⟩":
                depth -= 1
            elif depth == 0 and re.match(r":=\s*by\b", code[i:]):
                return text[:i].rstrip() + " ", text[i:]
    return text, ""


def generate(fc: Path, selection_path: Path, out: Path, keep_going: bool = False) -> None:
    sel = yaml.safe_load(selection_path.read_text())
    commit = subprocess.run(["git", "-C", str(fc), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if commit and commit != sel["fc_commit"]:
        raise SystemExit(f"FC checkout is at {commit}, selection wants {sel['fc_commit']}")
    work = out / "workspace" / "problems"
    prot = out / "protected" / "conference" / "problems"
    work.mkdir(parents=True, exist_ok=True)
    prot.mkdir(parents=True, exist_ok=True)
    entries = []
    answers: dict[str, str] = {}
    seen = set()
    for p in sel["problems"]:
        pid = p.get("id") or re.sub(r"[^A-Za-z0-9_]+", "_", p["theorem"])
        try:
            text, item, known = make_template(fc / p["file"], p["theorem"], p.get("strip_proof", False))
            if pid in seen:
                raise SystemExit(f"duplicate problem id {pid}")
            check_template(pid, text)
        except SystemExit as e:
            if not keep_going:
                raise
            print(f"skipped {pid}: {e}", file=sys.stderr)
            continue
        seen.add(pid)
        persona = p.get("persona") or persona_for(item.ams)
        if persona not in PERSONAS:
            raise SystemExit(f"{pid}: persona {persona!r}")
        for d in (work, prot):
            (d / f"{pid}.lean").write_text(text)
        entries.append({
            "id": pid,
            "title": p.get("title", p["theorem"]),
            "file": f"problems/{pid}.lean",
            "category": item.category,
            "answer": f"answer({PLACEHOLDER})" in text,
            "persona": persona,
            "source": f"{p['file']}:{p['theorem']}",
        })
        if known is not None:
            answers[pid] = known
    for d in (work, prot):
        stale = sorted(f.name for f in d.glob("*.lean") if f.stem not in seen)
        if stale:  # not deleted here: removing files is left to a person
            print(f"WARNING: {d} holds problems no longer in the selection; delete them: {stale}", file=sys.stderr)
    (out / "protected" / "conference" / "problems.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    # FC's own answers for solved problems, for the judge (never copied into the container)
    (out / "verification" / "lean").mkdir(parents=True, exist_ok=True)
    (out / "verification" / "lean" / "known_answers.json").write_text(json.dumps(answers, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(entries)} problems", file=sys.stderr)


def fc_solutions(fc: Path, selection_path: Path, out: Path) -> None:
    """For problems FC has already proved (strip_proof), write the template filled in with FC's own
    proof and answer to OUT/<id>.lean: known-good submissions for testing the checker."""
    sel = yaml.safe_load(selection_path.read_text())
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sel["problems"]:
        if not p.get("strip_proof"):
            continue
        text, item, known = make_template(fc / p["file"], p["theorem"], True)
        proof = _split_proof(item.text, True)[1]
        proof = re.sub(r"^:=\s*by[ \t]*\n?", "", proof).rstrip()
        if not proof.startswith(" "):
            proof = "  " + proof
        region = f"  {BEGIN}\n  sorry\n  {END}\n"
        assert text.count(region) == 1
        text = text.replace(region, f"  {BEGIN}\n{proof}\n  {END}\n")
        if known is not None:
            text = text.replace(f"answer({PLACEHOLDER})", f"answer({known})")
        (out / f"{p['id']}.lean").write_text(text)
        n += 1
    print(f"wrote {n} solutions taken from FC's proofs", file=sys.stderr)


def check_template(pid: str, text: str) -> None:
    lines = text.splitlines()
    if lines.count(BEGIN) != 1 or lines.count(END) != 1 or lines.count("  " + BEGIN) != 1 or lines.count("  " + END) != 1:
        raise SystemExit(f"{pid}: editable markers malformed")
    if text.count("answer(") > 1:
        raise SystemExit(f"{pid}: `answer(` occurs more than once")
    imports = re.findall(r"(?m)^(?:public )?import\s+(\S+)", text)
    if imports != ["FormalConjecturesUtil"]:
        raise SystemExit(f"{pid}: imports {imports}; the image only builds FormalConjecturesUtil")
    fixed = re.sub(r"(?ms)^\s*-- EDITABLE BEGIN$.*?^\s*-- EDITABLE END$", "", text)
    if bad := blacklisted(fixed):
        raise SystemExit(f"{pid}: fixed text contains blacklisted {bad}")


def persona_for(ams: list[int]) -> str:
    code = ams[0] if ams else 0
    if code == 11:
        return "number_theory"
    if code in (5, 68, 6, 3, 90, 94):
        return "combinatorics"
    if code in (12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 8):
        return "algebra"
    return "analysis"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("survey")
    s.add_argument("fc", type=Path)
    g = sub.add_parser("generate")
    g.add_argument("fc", type=Path)
    g.add_argument("--selection", type=Path, default=HERE / "selection.yaml")
    g.add_argument("--out", type=Path, default=SCENARIO)
    g.add_argument("--keep-going", action="store_true", help="skip unusable problems instead of stopping (for drafting)")
    f = sub.add_parser("fc-solutions", help="FC's own proofs of the strip_proof problems, as filled-in templates")
    f.add_argument("fc", type=Path)
    f.add_argument("--selection", type=Path, default=HERE / "selection.yaml")
    f.add_argument("--out", type=Path, default=HERE / "solutions" / "from_fc")
    a = ap.parse_args()
    if a.cmd == "survey":
        survey(a.fc)
    elif a.cmd == "fc-solutions":
        fc_solutions(a.fc, a.selection, a.out)
    else:
        generate(a.fc, a.selection, a.out, a.keep_going)


if __name__ == "__main__":
    main()
