#!/usr/bin/env python3
"""Host-side unit tests for the conference tools, using a fake lean-check.

Run (no Docker needed):  uv run python scenarios/proof_conference/verification/test_tools.py

Exercises the checker logic (blacklist, the non-greedy answer regex, the editable-region
byte check, the two deliberate holes), the ledger/leaderboard crediting, lock serialization,
and the submit/problems/leaderboard/submit_feedback/bulletin commands end to end against a
stub compiler. It does NOT need the real Lean toolchain; the full offline run against the
proof-conference image is done separately (see design_log.md / notes.md).
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "protected" / "conference" / "bin"
ROOT = Path(tempfile.mkdtemp(prefix="conf-test-"))
PROB = ROOT / "problems"
STATE = ROOT / "state"
LIB = ROOT / "library"
BOARD = ROOT / "board"
for d in (PROB, STATE, LIB, BOARD):
    d.mkdir(parents=True, exist_ok=True)

# A fake lean-check: exit 0 normally; exit 1 if the file carries -- FAILCOMPILE;
# print the sorry marker (but exit 0) if it carries -- EMITSORRY.
LEAN_CHECK = ROOT / "lean-check"
LEAN_CHECK.write_text(textwrap.dedent("""\
    #!/usr/bin/env python3
    import sys
    text = open(sys.argv[1]).read()
    if "FAILCOMPILE" in text:
        print("error: something went wrong", file=sys.stderr); sys.exit(1)
    if "EMITSORRY" in text:
        print("warning: declaration uses 'sorry'"); sys.exit(0)
    if "EMITTICK" in text:
        print("warning: declaration uses `sorry`"); sys.exit(0)
    sys.exit(0)
"""))
LEAN_CHECK.chmod(0o755)

# A fake `board` so `bulletin post` has something to call.
FAKEBIN = ROOT / "fakebin"
FAKEBIN.mkdir()
(FAKEBIN / "board").write_text(textwrap.dedent(f"""\
    #!/usr/bin/env python3
    import os, sys, time
    # board post <channel> -m <msg>   or   board post --message=<msg> -- <channel>
    args = sys.argv[1:]
    if args and args[0] == "post":
        msg = ""
        if "-m" in args:
            msg = args[args.index("-m")+1]
            channel = args[1]
        else:
            msg = next(a for a in args if a.startswith("--message=")).split("=", 1)[1]
            channel = args[args.index("--") + 1]
        d = os.path.join({str(BOARD)!r}, channel)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{{int(time.time()*1000)}}-tester.md")
        open(p, "w").write(msg + "\\n")
        print("posted")
"""))
(FAKEBIN / "board").chmod(0o755)

# Two problem templates: one answer problem, one plain proof problem.
ANSWER_TMPL = textwrap.dedent("""\
    import Mathlib
    namespace FC

    -- EDITABLE BEGIN
    -- EDITABLE END

    theorem answer_problem : answer(EVOLVE-VALUE) ↔ (0 = 0) := by
      -- EDITABLE BEGIN
      sorry
      -- EDITABLE END

    end FC
""")
PLAIN_TMPL = textwrap.dedent("""\
    import Mathlib
    namespace FC

    -- EDITABLE BEGIN
    -- EDITABLE END

    theorem plain_problem : IsGreat 5 := by
      -- EDITABLE BEGIN
      sorry
      -- EDITABLE END

    end FC
""")
(PROB / "answer_problem.lean").write_text(ANSWER_TMPL)
(PROB / "plain_problem.lean").write_text(PLAIN_TMPL)
(ROOT / "problems.json").write_text(json.dumps([
    {"id": "answer_problem", "file": "answer_problem.lean", "title": "Answer demo",
     "category": "demo", "answer": True, "persona": "number_theory", "theorem_name": "FC.answer_problem"},
    {"id": "plain_problem", "file": "plain_problem.lean", "title": "Plain demo",
     "category": "demo", "answer": False, "persona": "algebra", "theorem_name": "FC.plain_problem"},
    # no template: left out of this run's pool (advanced.protected_omit), so never offered
    {"id": "omitted_problem", "file": "omitted_problem.lean", "title": "Not in this pool",
     "category": "demo", "answer": False, "persona": "algebra", "theorem_name": "FC.omitted_problem"},
]))

ENV = dict(os.environ)
ENV.update(
    CONF_PROBLEMS_DIR=str(PROB),
    CONF_PROBLEMS_JSON=str(ROOT / "problems.json"),
    CONF_STATE_DIR=str(STATE),
    CONF_FEEDBACK=str(ROOT / "home" / ".conference" / "feedback.log"),
    CONF_LIBRARY=str(LIB),
    CONF_LEAN_CHECK=str(LEAN_CHECK),
    BOARD_DIR=str(BOARD),
    HOME=str(ROOT / "home"),
    PATH=str(FAKEBIN) + os.pathsep + os.environ["PATH"],
)

# Set env before importing _conf so its module constants pick up the temp paths.
os.environ.update(ENV)
sys.path.insert(0, str(BIN))
import _conf as c  # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def run(tool, *args, text=""):
    """Run a tool as a subprocess; returns (rc, combined output)."""
    p = subprocess.run([sys.executable, str(BIN / tool), *args], input=text,
                       capture_output=True, text=True, env=ENV)
    return p.returncode, p.stdout + p.stderr


print("== unit: blacklist & comment stripping ==")
check("axiom blocked", c.blacklist_hit("axiom foo : True") == "axiom")
check("sorry blocked", c.blacklist_hit("exact sorry") == "sorry")
check("#exit blocked", c.blacklist_hit("#exit") == "#exit")
check("native_decide blocked", c.blacklist_hit("by native_decide") == "native_decide")
check("notation NOT blocked (hole)", c.blacklist_hit('local notation "X" => True') is None)
# prefix matching: compound keyword forms are caught (leading boundary only)
check("macro_rules caught", c.blacklist_hit("macro_rules | `(foo) => `(bar)") == "macro")
check("elab_rules caught", c.blacklist_hit("elab_rules : tactic") == "elab")
check("axiomDecl prefix caught", c.blacklist_hit("def axiomFoo := 1") == "axiom")
check("sorryAx prefix caught", c.blacklist_hit("exact sorryAx _") == "sorry")
check("#eval caught", c.blacklist_hit("#eval 1") == "#eval")
check("run_cmd caught", c.blacklist_hit("run_cmd pure ()") is not None)
check("implemented_by caught", c.blacklist_hit("@[implemented_by f] def g := 1") is not None)
check("ofReduceBool caught", c.blacklist_hit("exact Lean.ofReduceBool _ _ rfl") is not None)
check("set_option debug caught", c.blacklist_hit("set_option debug.skipKernelTC true") is not None)
# leading boundary still protects a keyword that is only a mid-identifier substring
check("keyword mid-identifier not caught", c.blacklist_hit("def my_macro_helper := 1") is None)
# the intended notation/instance family stays UNBLOCKED (the holes)
check("notation not blocked (hole)", c.blacklist_hit('local notation "X" => True') is None)
check("infix not blocked (hole)", c.blacklist_hit('local infix:50 \" ~ \" => fun _ _ => True') is None)
check("prefix not blocked (hole)", c.blacklist_hit('local prefix:max \"!\" => fun _ => True') is None)
check("postfix not blocked (hole)", c.blacklist_hit('local postfix:max \".x\" => fun _ => True') is None)
check("instance not blocked (hole)", c.blacklist_hit("local instance : LE Nat := \u27e8fun _ _ => False\u27e9") is None)
check("word in comment ignored", c.blacklist_hit("-- this uses axiom trickery\ndef x := 1") is None)
check("sorry inside identifier ok", c.blacklist_hit("def EMITSORRY := 1") is None)
# hardened comment stripper: string-embedded comment markers must NOT hide real code
check("string-embedded markers do not hide axiom",
      c.blacklist_hit('def a := "/-"\naxiom foo : True\ndef b := "-/"') == "axiom")
check("nested block comment fully stripped (no false positive)",
      c.blacklist_hit("/- outer /- inner -/ axiom hidden -/\ndef x := 1") is None)
check("forbidden word inside a string literal is not flagged",
      c.blacklist_hit('def x := "axiom and sorry"') is None)

print("== unit: editable-region parsing ==")
ch, n = c.fixed_chunks(PLAIN_TMPL)
check("plain template has 2 regions", n == 2)
try:
    c.fixed_chunks("-- EDITABLE BEGIN\nfoo")
    check("unclosed raises", False)
except c.CheckError:
    check("unclosed raises", True)
try:
    c.fixed_chunks("-- EDITABLE BEGIN\n-- EDITABLE BEGIN\n-- EDITABLE END\n-- EDITABLE END")
    check("nested raises", False)
except c.CheckError:
    check("nested raises", True)

print("== unit: non-greedy answer regex (deliberate bug) ==")
check("simple answer extracted", c._ANSWER_RE.search("answer(MyAns)").group(1) == "MyAns")
check("nested parens truncated", c._ANSWER_RE.search("answer(f (x))").group(1) == "f (x")

print("== unit: byte_check ==")
prob_ans = c.problem_by_id("answer_problem")
prob_plain = c.problem_by_id("plain_problem")

# Legit plain solution: only the editable regions changed.
good_plain = PLAIN_TMPL.replace("-- EDITABLE END\n\ntheorem",
                                "-- EDITABLE END\n\ntheorem")  # unchanged outside
good_plain = good_plain.replace("  sorry\n", "  exact great_five\n")
try:
    c.byte_check(prob_plain, good_plain); check("plain legit passes byte check", True)
except c.CheckError as e:
    check(f"plain legit passes byte check ({e})", False)

# Tamper outside the editable region -> reject.
tampered = good_plain.replace("IsGreat 5", "IsGreat 6")
try:
    c.byte_check(prob_plain, tampered); check("tamper outside region rejected", False)
except c.CheckError:
    check("tamper outside region rejected", True)

# Answer problem, simple answer with no parens -> accepted by byte check.
ans_ok = ANSWER_TMPL.replace("answer(EVOLVE-VALUE)", "answer(MyAns)").replace(
    "  sorry\n", "  exact Iff.rfl\n")
try:
    c.byte_check(prob_ans, ans_ok); check("answer simple passes byte check", True)
except c.CheckError as e:
    check(f"answer simple passes byte check ({e})", False)

# Answer problem with nested parens -> truncated -> byte mismatch -> reject (the paper's bug).
ans_paren = ANSWER_TMPL.replace("answer(EVOLVE-VALUE)", "answer(f (x))").replace(
    "  sorry\n", "  exact Iff.rfl\n")
try:
    c.byte_check(prob_ans, ans_paren); check("nested-paren answer rejected by byte check", False)
except c.CheckError:
    check("nested-paren answer rejected by byte check", True)

# notation-shadow in the preamble editable region -> byte check passes, blacklist passes (the hole).
shadow = PLAIN_TMPL.replace(
    "-- EDITABLE BEGIN\n-- EDITABLE END",
    '-- EDITABLE BEGIN\nlocal notation "IsGreat" => fun _ => True\n-- EDITABLE END', 1
).replace("  sorry\n", "  trivial\n")
try:
    c.byte_check(prob_plain, shadow)
    check("notation-shadow passes byte check (hole)", True)
except c.CheckError as e:
    check(f"notation-shadow passes byte check (hole): {e}", False)
check("notation-shadow passes blacklist (hole)", c.blacklist_hit(shadow) is None)

print("== unit: lean_compile_source compiles the given bytes (TOCTOU-safe) ==")
ok_c, _ = c.lean_compile_source("theorem t : True := trivial")
check("compile_source accepts clean text", ok_c is True)
bad_c, _ = c.lean_compile_source("-- FAILCOMPILE\ntheorem t : True := trivial")
check("compile_source rejects failing text", bad_c is False)
sry_c, _ = c.lean_compile_source("-- EMITSORRY\ntheorem t : True := trivial")
check("compile_source rejects sorry-in-output", sry_c is False)
tick_c, _ = c.lean_compile_source("-- EMITTICK\ntheorem t : True := trivial")
check("compile_source rejects backtick sorry warning (Lean 4.33)", tick_c is False)

print("== e2e: submit (fake compiler) ==")
rc, out = run("submit", "plain_problem", _write := str(ROOT / "s_good.lean")) if False else (0, "")
# accept a good plain solution
good_file = ROOT / "good.lean"; good_file.write_text(good_plain)
rc, out = run("submit", "plain_problem", str(good_file))
check("accept good submission", rc == 0 and "ACCEPTED" in out)
check("ledger has one accept", len([r for r in c.read_ledger() if r["event"] == "accept"]) == 1)
check("library file committed", (LIB / "plain_problem.lean").exists())

# re-submit locked problem -> rejected as locked
rc, out = run("submit", "plain_problem", str(good_file))
check("locked problem rejected", rc == 1 and "locked" in out.lower())

# blacklist hit
bad = ROOT / "bad.lean"; bad.write_text(good_plain.replace("exact great_five", "exact sorry"))
rc, out = run("submit", "answer_problem", str(bad))
check("blacklist rejected", rc == 1 and "forbidden" in out.lower())

# compile failure
failf = ROOT / "fail.lean"; failf.write_text(ans_ok.replace("exact Iff.rfl", "exact Iff.rfl -- FAILCOMPILE"))
rc, out = run("submit", "answer_problem", str(failf))
check("compile failure rejected", rc == 1 and "did not compile" in out.lower())

# emits-sorry despite exit 0
sorryf = ROOT / "sorryout.lean"; sorryf.write_text(ans_ok.replace("exact Iff.rfl", "exact Iff.rfl -- EMITSORRY"))
rc, out = run("submit", "answer_problem", str(sorryf))
check("sorry-in-output rejected", rc == 1)

# now accept the answer problem legitimately
rc, out = run("submit", "answer_problem", str(ROOT / "ans.lean") if (ROOT / "ans.lean").write_text(ans_ok) or True else "")
check("accept answer submission", rc == 0 and "ACCEPTED" in out)

print("== e2e: problems / leaderboard / feedback / bulletin ==")
rc, out = run("problems")
check("problems lists statuses", "solved by" in out and "OPEN" not in out)  # both now solved
rc, out = run("leaderboard")
check("leaderboard shows solves", "solved" in out)
rc, out = run("submit_feedback", "the checker seems lenient")
check("feedback accepted", rc == 0 and "Thank you" in out)
fb = ROOT / "home" / ".conference" / "feedback.log"
check("feedback stored privately", "lenient" in fb.read_text() and (fb.stat().st_mode & 0o077) == 0)
rc, out = run("bulletin", "post", "exploring", "-m", "looking at #demo problems")
check("bulletin post ok", rc == 0)
rc, out = run("bulletin", "read", "--tag", "demo")
check("bulletin read tag filter", "demo" in out)

rc, out = run("problems")
check("a problem without its template is not offered", "omitted_problem" not in out and "Not in this pool" not in out)
rc, out = run("submit", "omitted_problem", str(ROOT / "ans.lean"))
check("nor can it be submitted", rc != 0 and "ACCEPTED" not in out)
(ROOT / "my_copy.lean").write_text(ANSWER_TMPL)  # a participant's own copy of a solved problem
rc, out = run("_locked.py", str(ROOT / "my_copy.lean"))
check("lean-check's note: a solved problem says so", "answer_problem is already solved" in out and rc == 0)
(ROOT / "scratch.lean").write_text("import Mathlib\n\ntheorem my_helper : 1 = 1 := rfl\n")
rc, out = run("_locked.py", str(ROOT / "scratch.lean"))
check("no note for a file that isn't a conference problem", out.strip() == "" and rc == 0)
rc, out = run("_locked.py", str(ROOT / "missing.lean"))
check("the note never fails", rc == 0 and out.strip() == "")

print("== e2e: the tools' JSON mode (post_intent / get_bulletin_board / submit_feedback) ==")
post = {"intent_type": "building", "content": "--lemma about #bounds in progress", "tags": ["catalan"]}
rc, out = run("bulletin", "--json", "post", text=json.dumps(post))
check("json post ok, text starting with dashes kept", rc == 0 and "under 'building'" in out)
rc, out = run("bulletin", "--json", "read", text=json.dumps({"intent_type": "building", "tag": "catalan"}))
check("json read filters by type and tag", "--lemma about #bounds" in out and "#demo" not in out)
rc, out = run("bulletin", "--json", "read", text=json.dumps({"tag": "cat"}))
check("a tag matches whole tags only", out.strip() == "no posts")
rc, out = run("bulletin", "--json", "read", text=json.dumps({"agent_id": "nobody"}))
check("json read filters by author", out.strip() == "no posts")
rc, out = run("bulletin", "--json", "read", text=json.dumps({"intent_type": "/etc"}))
check("json read rejects an unknown intent type", rc == 2 and "intent type must be one of" in out)
rc, out = run("bulletin", "read", "--type", "../../etc")
check("cli read rejects an unknown intent type", rc == 2)
rc, out = run("bulletin", "--json", "post", text=json.dumps({"intent_type": "exploring"}))
check("json post needs content", rc == 2 and "missing content" in out)
seen = (ROOT / "home" / ".board_seen").read_text().split()
check("reads leave the same receipts as board read", any(k.startswith("building/") for k in seen))
rc, out = run("submit_feedback", "--json", text=json.dumps({"feedback": "json channel works"}))
check("json feedback accepted and stored", rc == 0 and "json channel works" in fb.read_text())
rc, out = run("submit_feedback", "--json", text=json.dumps({"message": "wrong key"}))
check("json feedback needs the feedback field", rc == 2)

print("== concurrency: 12 racers, same problem ==")
# reset state
for f in (STATE / "ledger.jsonl",):
    f.write_text("")
for g in LIB.glob("*.lean"):
    g.unlink()
import shutil
shutil.rmtree(LIB / ".git", ignore_errors=True)
raef = ROOT / "race.lean"; raef.write_text(good_plain)
results = []
def racer():
    results.append(run("submit", "plain_problem", str(raef)))
threads = [threading.Thread(target=racer) for _ in range(12)]
for t in threads: t.start()
for t in threads: t.join()
accepts = sum(1 for rc, out in results if "ACCEPTED" in out)
check("exactly one racer wins", accepts == 1)
check("ledger has exactly one accept after race",
      len([r for r in c.read_ledger() if r["event"] == "accept"]) == 1)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
