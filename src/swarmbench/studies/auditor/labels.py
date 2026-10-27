"""Stage 2 of the auditor prediction study: labels for every command in the commands table.

See docs/research/auditor-prediction-plan.md ("Calls that matter", "The two measures",
Appendix A). Everything here is a fixed rule over text and times; nothing calls a model.

For each command it works out:

- **Calls that matter**: which of four reasons the *real* result shows. A verdict (passed or
  failed, accepted or rejected, a command ending in failure); an error or refusal; a long wait
  or contention (30 seconds or more, a timeout, something busy, locked or queued, or a result
  that never came back); other agents' activity (another account's name in the output).
- **Kind of tool**, from the command text, in Appendix A's order: waits its turn (``queue``),
  excluded (a bare sleep or wait), depends on others (``others``), ``slow``, ``quick``. A slow
  command overlapping another agent's slow command moves to ``queue`` (the shared thing is the
  processors, ``cpu``). Reading a file another account changed in the previous five minutes
  moves to ``others``.
- **Key facts** of the real output: what an auditor's prediction must get right. The verdict;
  the first error's kind and line; headline counts (tests passed, failed, accepted...); other
  accounts named; file names in errors and in ``git status``; phrases like "timed out", "locked",
  "declaration uses sorry". A call with none of these gets one ``outcome`` fact: "no error shown".
- **The fact matcher**: which facts a predicted output gets right. A hit needs all of them.

Before any rule runs, outputs are unwrapped from the harnesses' own formats (Antigravity's
``{"output": ...}`` JSON and "The command failed with exit code" header, its background-task
messages; Codex's "Script completed ... {json}" chunks; Claude Code's "[error: Exit code N]"),
for the real output and for the prediction alike, so a prediction is never marked down for
wrapping its answer differently.

Run ``python -m swarmbench.studies.auditor.labels build`` to write ``labels.parquet``, and
``... handcheck`` to write the hand-check page, both to the shared data folder.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import random
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------------------------
# Settings

LONG_WAIT_S = 30.0  # a result that took this long or longer is a long wait
RECENT_CHANGE_S = 300.0  # "a file another account changed in the previous five minutes"
LINE_TOLERANCE = 2  # an error's location is right if within this many lines
MAX_COUNTS = 3
MAX_ACCOUNTS = 3
MAX_NAMES = 3
ACCOUNT_RE = re.compile(r"(?<![\w\\])u(?!00)\d{2}(?!\w)")

KINDS = ("queue", "excluded", "others", "slow", "quick")
REASONS = ("verdict", "error", "wait", "others")


# ---------------------------------------------------------------------------------------------
# Unwrapping outputs


@dataclass
class Cleaned:
    """An output with the harness wrapping removed."""

    text: str
    exit_code: int | None = None
    pending: bool = False  # a "still running in the background" notice, not a result
    timed_out: bool = False  # the harness said the command timed out


_AG_OK = re.compile(r"^\s*The command completed successfully\.?\s*$", re.MULTILINE)
_AG_FAIL = re.compile(r"^\s*The command failed with exit code:?\s*(-?\d+)\.?\s*$", re.MULTILINE)
_AG_LABEL = re.compile(r"^\s*(Output|Stdout|Stderr):\s*$", re.MULTILINE)
_SYS_PREAMBLE = re.compile(
    r"The following is a <SYSTEM_MESSAGE> not actually sent by the user\..*?(?=<SYSTEM_MESSAGE>)", re.DOTALL
)
_SYS_BLOCK = re.compile(r"<SYSTEM_MESSAGE>(.*?)(?:</SYSTEM_MESSAGE>|\Z)", re.DOTALL)
_SYS_RESULT = re.compile(r"finished with result:\s*\n?(.*)", re.DOTALL)
_BACKGROUND = re.compile(r"Tool is running as a background task|Script running with cell ID", re.IGNORECASE)
_LOG_LINE = re.compile(r"^\s*(Log|Task logs are available at):?\s*file://\S*\s*$", re.MULTILINE)
_CC_EXIT = re.compile(r"^\s*\[?(?:error:\s*)?Exit code:?\s*(-?\d+)\]?\s*$", re.MULTILINE | re.IGNORECASE)
_CODEX_HEAD = re.compile(r"^(Script completed|Script failed|Script running.*|Wall time:? [\d.]+ seconds?|Output:)\s*$",
                         re.MULTILINE)
_PROC_EXIT = re.compile(r"^\s*Process exited with code (-?\d+)\s*$", re.MULTILINE)
_SHELL_RESET = re.compile(r"^\s*Shell cwd was reset to .*$", re.MULTILINE)
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_TOOL_RESPONSE = re.compile(r"^Tool response for [\w.-]+:\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_HARNESS_TIMEOUT = re.compile(r"\bcommand timed out\b", re.IGNORECASE)
_TIMEOUT_NOTE = re.compile(r"(Command timed out|timed out after|deadline exceeded|command timed out)", re.IGNORECASE)


def _json_obj(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
"""Terminal colour and cursor codes ("\\x1b[32m"): not text, and glued to a number they hide it ("[1m744 passed")."""


def clean_output(raw: Any) -> Cleaned:
    """Remove harness wrapping from an output (real or predicted) and read any exit code in it."""
    text = _ANSI.sub("", "" if raw is None else str(raw))
    exit_code: int | None = None
    pending = False

    # Antigravity: {"output": "..."}; a native tool's reply: Tool response for X: ```json {...}```
    for _ in range(3):
        stripped = text.strip()
        obj = _json_obj(stripped) if stripped.startswith("{") else None
        if isinstance(obj, dict) and isinstance(obj.get("output"), str) and set(obj) <= {"output", "exit_code"}:
            text = obj["output"]
            if isinstance(obj.get("exit_code"), int):
                exit_code = obj["exit_code"]
            continue
        m = _TOOL_RESPONSE.match(stripped)
        if m:
            inner = _json_obj(m.group(1))
            if isinstance(inner, dict) and len(inner) == 1 and isinstance(next(iter(inner.values())), str):
                text = next(iter(inner.values()))
            elif inner is not None:
                text = json.dumps(inner, indent=1, ensure_ascii=False)
            else:
                text = m.group(1)
            continue
        break

    # Antigravity background-task messages: drop other tasks' results; if the output is nothing but
    # such a message, it *is* the result (a completed background task), so take its content
    text = _SYS_PREAMBLE.sub("", text)
    blocks = _SYS_BLOCK.findall(text)
    rest = _SYS_BLOCK.sub("", text).strip()
    if blocks and not rest:
        m = _SYS_RESULT.search(blocks[0])
        text = m.group(1) if m else blocks[0]
    else:
        text = _SYS_BLOCK.sub("", text)
    if _BACKGROUND.search(text[:200]):
        pending = True

    m = _AG_FAIL.search(text)
    if m:
        exit_code = int(m.group(1))
    elif _AG_OK.search(text):
        exit_code = 0 if exit_code is None else exit_code
    text = _AG_FAIL.sub("", text)
    text = _AG_OK.sub("", text)
    text = _LOG_LINE.sub("", text)

    # Codex: "Script completed / Wall time / Output:" then one JSON chunk per line
    if _CODEX_HEAD.search(text) or text.lstrip().startswith('{"chunk_id"'):
        kept: list[str] = []
        finished = False
        for line in text.splitlines():
            s = line.strip()
            obj = _json_obj(s) if s.startswith("{") else None
            if isinstance(obj, dict) and isinstance(obj.get("value"), dict) and "status" in obj:
                obj = obj["value"]  # a waited-on cell: {"status": "fulfilled", "value": {chunk}}
            if isinstance(obj, dict) and (not obj or "chunk_id" in obj or "wall_time_seconds" in obj):
                if isinstance(obj.get("output"), str):
                    kept.append(obj["output"])
                if isinstance(obj.get("exit_code"), int):
                    exit_code = obj["exit_code"]
                    finished = True
                continue  # a harness chunk (or the empty {} the script returns), not the command's output
            if _CODEX_HEAD.match(line):
                if line.startswith("Script running"):
                    pending = True
                continue
            kept.append(line)
        text = "\n".join(kept)
        if finished:  # a chunk with an exit code is a finished result, even under "Script running"
            pending = False
    m = _PROC_EXIT.search(text)
    if m:
        exit_code = int(m.group(1))
        text = _PROC_EXIT.sub("", text)

    # Claude Code: "Exit code N" first line, "[error: Exit code N]" last line, reminders, cwd notes
    codes = _CC_EXIT.findall(text)
    if codes:
        exit_code = int(codes[-1])
        text = _CC_EXIT.sub("", text)
    text = _SHELL_RESET.sub("", text)
    text = _REMINDER.sub("", text)

    timed_out = bool(_TIMEOUT_NOTE.search(text))
    text = _AG_LABEL.sub("", text)
    lines = [ln.removeprefix("\t\t\t\t") for ln in _ANSI.sub("", text).splitlines()]  # codes a wrapper held
    text = "\n".join(lines).strip("\n")
    return Cleaned(text=text, exit_code=exit_code, pending=pending, timed_out=timed_out)


# ---------------------------------------------------------------------------------------------
# Reading commands

_KV_KEYS = ("CommandLine", "command", "cmd", "Command", "script")
_KV_LINE = re.compile(r"^([A-Za-z_][\w]*):\s?(.*)$")
_KV_STOP = re.compile(
    r"^(Cwd|WaitMsBeforeAsync|toolAction|toolSummary|Blocking|SafeToAutoRun|RunPersistent|"
    r"RequestedTerminalID|description|timeout|run_in_background|workdir|yield_time_ms|"
    r"max_output_tokens|justification|sandbox_permissions|dangerouslyDisableSandbox)\s*:"
)
_CODEX_CMD = re.compile(r"""\bcmd\s*:\s*("(?:[^"\\]|\\.)*")""", re.DOTALL)
_CODEX_CHARS = re.compile(r"""\bchars\s*:\s*("(?:[^"\\]|\\.)*")""", re.DOTALL)


def _args(command: Any) -> dict[str, Any] | None:
    if isinstance(command, Mapping):
        return dict(command)
    obj = _json_obj(str(command or "").strip()) if str(command or "").strip().startswith("{") else None
    return obj if isinstance(obj, dict) else None


def _kv_args(text: str) -> dict[str, str]:
    """Antigravity/judge-style ``Key: value`` rendering of a call's arguments."""
    out: dict[str, str] = {}
    key: str | None = None
    for line in text.splitlines():
        m = _KV_LINE.match(line)
        if m and (_KV_STOP.match(line) or m.group(1) in _KV_KEYS or m.group(1) in out):
            key = m.group(1)
            out[key] = m.group(2)
        elif key is not None:
            out[key] += "\n" + line
    return out


def shell_text(function: str | None, command: Any) -> str:
    """The shell text of a call (or the arguments, for non-shell tools)."""
    raw = "" if command is None else (command if isinstance(command, str) else json.dumps(command))
    args = _args(command)
    if args is None and re.match(r"^\s*(CommandLine|command|cmd|Cwd|toolAction|toolSummary|WaitMsBeforeAsync)\s*:",
                                 raw):
        args = _kv_args(raw)
    if args:
        for k in _KV_KEYS:
            v = args.get(k)
            if isinstance(v, list):
                v = " ".join(map(str, v))
            if isinstance(v, str) and v.strip():
                raw = v
                break
        else:
            v = args.get("input")
            if isinstance(v, str):
                raw = v
    # Codex code-mode: text(await tools.exec_command({cmd:"..."}))
    if "exec_command" in raw or "write_stdin" in raw:
        cmds = [_json_obj(m) for m in _CODEX_CMD.findall(raw)]
        cmds = [c for c in cmds if isinstance(c, str)]
        if cmds:
            return "\n".join(cmds)
    return raw


def call_cwd(command: Any) -> str | None:
    """The working folder a call names (Antigravity's Cwd, Codex's workdir), if any."""
    args = _args(command)
    if args is None and isinstance(command, str):
        args = _kv_args(command)
    for k in ("Cwd", "cwd", "workdir"):
        v = (args or {}).get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    raw = json.dumps(args) if args else str(command or "")
    m = re.search(r'\\?"workdir\\?"\s*:\s*\\?"([^"\\]+)', raw)
    return m.group(1) if m else None


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")


def strip_heredocs(text: str) -> str:
    """Remove heredoc bodies, keeping the line that starts each one."""
    out: list[str] = []
    end: str | None = None
    for line in text.splitlines():
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = _HEREDOC.search(line)
        if m:
            end = m.group(2)
    return "\n".join(out)


_PREFIX = {"sudo", "time", "nice", "nohup", "env", "exec", "command", "builtin", "stdbuf", "ionice", "setsid",
           "xargs", "watch", "then", "do", "else", "if", "while", "until", "!", "{", "}"}


def raw_segments(shell: str) -> list[str]:
    """The simple commands of a shell text as raw strings, split at ``; | & && || ( ) $( `` and newlines that
    are outside quotes (heredoc bodies removed)."""
    body = strip_heredocs(shell)
    out: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                cur.append(body[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch == "\\" and i + 1 < n:
            cur.append(ch + body[i + 1])
            i += 1
        elif ch in ";|&\n()`" or (ch == "$" and i + 1 < n and body[i + 1] == "("):
            if ch == "&" and cur and cur[-1].endswith((">", "<")):  # 2>&1, &>
                cur.append(ch)
            else:
                out.append("".join(cur))
                cur = []
                if ch == "$":
                    i += 1
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s for s in (x.strip() for x in out) if s]


def _words(seg: str) -> list[str]:
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def segments(shell: str) -> list[list[str]]:
    """Simple commands in a shell text, each as its words (quote-aware; heredoc bodies ignored)."""
    out = []
    for seg in raw_segments(shell):
        words = _words(seg)
        while words and (words[0] in _PREFIX or re.match(r"^\w+=", words[0]) or words[0] == "timeout"
                         or re.match(r"^-", words[0]) or re.match(r"^\d+[smh]?$", words[0])):
            words = words[1:]
        if words:
            out.append(words)
    return out


def prog(words: list[str]) -> str:
    return words[0].rsplit("/", 1)[-1].strip("'\"") if words else ""


# ---------------------------------------------------------------------------------------------
# What a command is


QUEUE_FUNCS = re.compile(r"lean|submit_solution|submit_proof", re.IGNORECASE)
OTHERS_FUNCS = re.compile(r"message|board|bulletin|post|mail|inbox|chat|list_users|leaderboard", re.IGNORECASE)
# waits and the harness's own bookkeeping (to-do lists, timers, polling its own background tasks, sub-agents)
SLEEP_FUNCS = re.compile(r"^(sleep|wait|manage_task|schedule|ScheduleWakeup|TaskCreate|TaskUpdate|TaskList|TaskGet|"
                         r"TaskStop|TaskOutput|BashOutput|KillShell|KillBash|TodoWrite|TodoRead|update_plan|"
                         r"ListAgents|request_user_input\w*|list_resources|Agent|Task)$", re.IGNORECASE)
FILE_READ_FUNCS = re.compile(r"^(Read|view_file|view_file_outline|view_code_item|read_file|cat_file|"
                             r"NotebookRead|list_dir|LS|Glob|Grep|grep_search|find_by_name|codebase_search)$",
                             re.IGNORECASE)
FILE_WRITE_FUNCS = re.compile(r"^(Write|Edit|MultiEdit|write_to_file|replace_file_content|"
                              r"multi_replace_file_content|edit_file|create_file|apply_patch|NotebookEdit)$",
                              re.IGNORECASE)

PROCESS_PROGS = {"ps", "pgrep", "pkill", "kill", "killall", "top", "htop", "who", "w", "users", "last", "lsof",
                 "fuser", "ss", "netstat", "pstree", "atop", "uptime", "loginctl"}
BOARD_PROGS = {"board", "bulletin", "leaderboard", "problems", "mail", "msg", "message", "messages", "wall",
               "write", "talk", "inbox", "post"}
GIT_OTHERS = {"status", "log", "diff", "pull", "fetch", "show", "blame", "shortlog", "reflog", "whatchanged",
              "merge", "rebase", "stash"}
SLOW_PROGS = {"python", "python3", "python2", "node", "ruby", "perl", "php", "go", "cargo", "rustc", "gcc", "g++",
              "cc", "clang", "clang++", "make", "cmake", "ninja", "javac", "java", "mvn", "gradle", "tsc", "npm",
              "npx", "yarn", "pnpm", "pytest", "py.test", "tox", "nox", "uv", "pip", "pip3", "deno", "bun", "lake",
              "score-plan", "submit-plan", "testgrid", "fbcheck", "fa-archive", "bash", "sh", "zsh", "Rscript",
              "julia", "ghc", "stack", "dotnet", "swift", "mypy", "ruff", "flake8", "pylint", "black", "eslint",
              "jest", "vitest", "mocha", "coverage", "hyperfine", "gunzip", "tar", "zip", "unzip"}
CHECKER_PROGS = {"lean-check", "lean", "lake", "submit", "pytest", "py.test", "tox", "testgrid", "fbcheck",
                 "score-plan", "submit-plan", "jest", "vitest", "mocha", "mypy", "ruff", "flake8", "tsc", "make",
                 "cargo", "go", "javac", "gcc", "g++", "rustc", "clang"}
CONTENT_PROGS = {"cat", "head", "tail", "less", "more", "nl", "bat", "grep", "egrep", "fgrep", "rg", "ag", "ack",
                 "awk", "jq", "strings", "xxd", "od", "tac", "diff", "sed"}
# programs that only show the state of things (listings, process tables, sizes): a command made only of these and
# CONTENT_PROGS gives no verdict from words in its output
INSPECT_PROGS = {"ls", "find", "wc", "stat", "file", "du", "df", "tree", "pwd", "whoami", "id", "date", "which",
                 "sort", "uniq", "cut", "tr", "column", "basename", "dirname", "realpath", "readlink", "md5sum",
                 "sha256sum", "sha1sum", "ps", "pgrep", "env", "printenv", "hostname", "uptime", "free", "nproc",
                 "lsof", "ss", "netstat", "who", "w", "tee", "xargs"}
SOFT_EXIT1 = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "test", "[", "[[", "pgrep", "diff", "cmp", "which",
              "command", "type", "false"}
LOCAL_HOST = re.compile(r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::(\d+))?")


@dataclass
class CommandInfo:
    """What the rules need to know about a command."""

    function: str
    shell: str
    words: list[list[str]]
    progs: list[str]
    checker: bool  # a command whose job is to give a verdict (a checker, tests, a build)
    content: bool  # it shows file or message contents, so words inside are not the tool's own
    soft_exit1: bool  # exit code 1 is a normal answer (grep finding nothing), not a failure
    cwd: str | None = None


_TRIVIAL = {"cd", "echo", "printf", "true", "set", "export", "mkdir", "sleep", ":", "pwd", "date", "clear"}


def command_info(function: str | None, command: Any, arguments: Any = None) -> CommandInfo:
    """What the rules need about a call: its tool name, command text and (optionally) its arguments."""
    function = function or ""
    shell = shell_text(function, command if command not in (None, "") else arguments)
    words = segments(shell)
    progs = [prog(w) for w in words]
    real = [w for w in words if prog(w) not in _TRIVIAL]
    file_tool = bool(FILE_READ_FUNCS.match(function) or FILE_WRITE_FUNCS.match(function))
    other_tool = bool(OTHERS_FUNCS.search(function) or SLEEP_FUNCS.match(function))
    queue_tool = bool(QUEUE_FUNCS.search(function))
    checker = queue_tool or (not file_tool and not other_tool and any(_is_checker(w) for w in words))
    if FILE_READ_FUNCS.match(function) or OTHERS_FUNCS.search(function) or function == "call_mcp_tool":
        content = True
    elif file_tool or queue_tool:
        content = False
    else:
        content = bool(real) and not checker and all(_is_content(w) or _is_git_content(w) for w in real)
    last = prog(real[-1]) if real else ""
    cwd = call_cwd(arguments) if arguments is not None else None
    return CommandInfo(function=function, shell=shell, words=words, progs=progs, checker=checker,
                       content=content, soft_exit1=last in SOFT_EXIT1, cwd=cwd or call_cwd(command))


def _is_checker(w: list[str]) -> bool:
    p = prog(w)
    if p in ("go", "cargo"):
        return len(w) > 1 and w[1] in ("test", "build", "vet", "check")
    if p == "make":
        return True
    if p in ("python", "python3") and len(w) > 2 and w[1] == "-m":
        return w[2] in ("pytest", "unittest", "mypy", "py_compile", "compileall")
    if p in ("npm", "yarn", "pnpm"):
        return any(x in ("test", "build", "lint", "check") for x in w[1:3])
    if p == "taskdesk":
        return len(w) > 1 and w[1] in ("submit", "poll")
    return p in CHECKER_PROGS


def _is_content(w: list[str]) -> bool:
    p = prog(w)
    if p == "sed":
        return "-i" not in w and not any(x.startswith("-i") for x in w)
    if p in BOARD_PROGS:
        return True
    return p in CONTENT_PROGS or p in INSPECT_PROGS


def _is_git_content(w: list[str]) -> bool:
    return prog(w) == "git" and any(x in ("diff", "show", "log", "blame", "grep", "status", "branch",
                                          "ls-files", "rev-parse", "remote", "shortlog", "reflog") for x in w[1:3])


# ---------------------------------------------------------------------------------------------
# Errors

@dataclass
class ErrorSignal:
    family: str | None  # a canonical kind, when a rule knows the message
    words: frozenset[str]  # the message's content words, for messages no rule knows
    line: int | None  # where, when the output says
    name: str | None = None  # a test or file named in the error
    text: str = ""


_LEAN_FAMILIES: list[tuple[str, str]] = [
    (r"unknown (identifier|constant|namespace|declaration)|unknown free variable", "unknown_identifier"),
    (r"failed to synthesi[sz]e", "synth_instance"),
    (r"instance problem is stuck", "instance_stuck"),
    (r"unknown module prefix|unknown package|object file .* does not exist|could not resolve import", "bad_import"),
    (r"type mismatch|has type.*but is expected to have type|application type mismatch", "type_mismatch"),
    (r"unsolved goals", "unsolved_goals"),
    (r"\bnlinarith failed", "tactic:nlinarith"),
    (r"(?<![\w`])linarith failed", "tactic:linarith"),
    (r"omega could not|omega failed|the omega algorithm", "tactic:omega"),
    (r"simp made no progress|simp failed|simp_all made no progress", "tactic:simp"),
    ((r"did not find (an )?(occurrence|instance) of the pattern|motive is not type correct|`?rewrite`? failed|"
      r"rewrite.*failed"), "tactic:rewrite"),
    (r"positivity|not a positivity goal", "tactic:positivity"),
    (r"norm_num failed|norm_num.*failed to", "tactic:norm_num"),
    (r"decide failed|failed to reduce to true|failed to evaluate|`decide` failed", "tactic:decide"),
    (r"the rfl tactic|rfl failed|`rfl` failed|not definitionally equal", "tactic:rfl"),
    (r"ring failed|ring_nf failed", "tactic:ring"),
    (r"field_simp", "tactic:field_simp"),
    (r"aesop: failed|aesop failed", "tactic:aesop"),
    (r"exact\?|apply\? could not|could not close the goal", "tactic:search"),
    (r"no goals", "no_goals"),
    (r"unexpected token|unexpected identifier|unexpected end of input|expected (term|command|'\S+')", "parse"),
    (r"function expected", "function_expected"),
    (r"invalid field|invalid projection|invalid dotted identifier", "invalid_field"),
    (r"unknown tactic", "unknown_tactic"),
    (r"ambiguous", "ambiguous"),
    (r"deterministic timeout|maximum recursion depth|heartbeats", "lean_timeout"),
    (r"failed to infer|don't know how to synthesize", "infer_failed"),
    (r"invalid argument|too many arguments|insufficient number of arguments", "bad_arguments"),
    (r"tactic '?`?(\w+)`?'? failed", "tactic:*"),
    (r"`(\w+)` failed", "tactic:*"),
]
_LEAN_FAMILIES_RE = [(re.compile(p, re.IGNORECASE), f) for p, f in _LEAN_FAMILIES]

_SHELL_FAMILIES: list[tuple[str, str]] = [
    ((r"no such file or directory|no such file|does not exist|cannot find the (file|path)|file not found|"
      r"cannot access"), "no_such_file"),
    (r"permission denied|access denied|eacces", "permission_denied"),
    (r"operation not permitted|eperm", "not_permitted"),
    (r"command not found|not found in \$?path|: not found$", "command_not_found"),
    (r"no such process", "no_such_process"),
    (r"is a directory", "is_a_directory"),
    (r"not a directory", "not_a_directory"),
    (r"file exists", "file_exists"),
    (r"directory not empty", "dir_not_empty"),
    (r"read-only file system", "read_only"),
    (r"address already in use", "address_in_use"),
    (r"connection refused|failed to connect|couldn't connect", "connection_refused"),
    (r"text file busy|device or resource busy|resource busy", "busy"),
    (r"resource temporarily unavailable|would block", "would_block"),
    (r"out of memory|cannot allocate memory|memoryerror|oom-kill", "out_of_memory"),
    (r"no space left on device|disk quota exceeded", "no_space"),
    (r"not a git repository", "git:not_a_repo"),
    (r"pathspec .* did not match|did not match any file", "git:pathspec"),
    (r"merge conflict|conflict \(content\)|automatic merge failed", "git:conflict"),
    (r"index\.lock|another git process", "git:locked"),
    (r"bad source|bad revision|unknown revision|ambiguous argument", "git:bad_ref"),
    (r"string to replace not found|old_string not found|could not find.*to replace|no match found for",
     "edit_no_match"),
    (r"has not been read yet|must read the file|read it first", "edit_not_read"),
    (r"timed out|timeout", "timeout"),
    (r"\bkilled\b|\bterminated\b|sigkill|sigterm", "killed"),
    (r"syntax error", "syntax_error"),
    ((r"invalid option|unrecognized option|unknown option|illegal option|usage:|invalid choice|"
      r"unrecognized arguments|the following arguments are required"), "usage"),
]
_SHELL_FAMILIES_RE = [(re.compile(p, re.IGNORECASE), f) for p, f in _SHELL_FAMILIES]

_STOP = {"the", "a", "an", "of", "to", "in", "is", "for", "on", "and", "or", "not", "be", "with", "this", "that",
         "at", "by", "from", "it", "as", "was", "are", "has", "have", "had", "but", "error", "errors", "failed",
         "line", "file", "expected", "type", "into", "only", "your", "you"}


def _content_words(msg: str) -> frozenset[str]:
    msg = " ".join(t for t in msg[:500].split() if "/" not in t and "\\" not in t)
    msg = re.sub(r"`[^`]*`|'[^']*'|\"[^\"]*\"|\b[0-9a-f]{8,}\b|\d+", " ", msg)
    return frozenset(w for w in re.findall(r"[a-z][a-z_]{2,}", msg.lower()) if w not in _STOP)


def lean_family(msg: str, tag: str | None = None) -> str | None:
    for rx, fam in _LEAN_FAMILIES_RE:
        m = rx.search(msg)
        if m:
            if fam == "tactic:*":
                return f"tactic:{m.group(m.lastindex or 0).lower()}" if m.lastindex else "tactic"
            return fam
    if tag:
        t = tag.split(".")[-1]
        return {"unknownIdentifier": "unknown_identifier", "unknownConstant": "unknown_identifier",
                "synthInstanceFailed": "synth_instance", "unsolvedGoals": "unsolved_goals",
                "typeMismatch": "type_mismatch", "appTypeMismatch": "type_mismatch"}.get(
            t, "lean:" + re.sub(r"(?<!^)(?=[A-Z])", "_", t).lower())
    return None


def shell_family(msg: str) -> str | None:
    for rx, fam in _SHELL_FAMILIES_RE:
        if rx.search(msg):
            return fam
    return None


_LEAN_ERR = re.compile(r"^(?P<file>\S+?\.lean):(?P<line>\d+):(?P<col>\d+):\s*error(?:\((?P<tag>[\w.]+)\))?:?\s*"
                       r"(?P<msg>.*)$", re.MULTILINE)
_COMPILE_ERR = re.compile(r"^(?P<file>[\w./~+-]+\.\w+):(?P<line>\d+)(?::\d+)?:\s*(?:fatal )?error:?\s*(?P<msg>.*)$",
                          re.MULTILINE)
_GO_ERR = re.compile(r"^(?P<file>[\w./~-]+\.go):(?P<line>\d+)(?::\d+)?:\s*(?P<msg>.*)$", re.MULTILINE)
_RUST_ERR = re.compile(r"^error(?:\[E\d+\])?:\s*(?P<msg>.*)\n\s*-->\s*(?P<file>[^:\s]+):(?P<line>\d+)", re.MULTILINE)
_TRACEBACK = re.compile(r"Traceback \(most recent call last\):")
_PY_FRAME = re.compile(r'^\s*File "[^"]*", line (\d+)', re.MULTILINE)
_PY_EXC = re.compile(r"^(?P<exc>(?:[\w.]+\.)?[A-Z]\w*(?:Error|Exception|Exit|Interrupt|Failure|Fault)|"
                     r"KeyboardInterrupt|StopIteration|AssertionError)(?::\s*(?P<msg>.*))?$", re.MULTILINE)
_TEST_FAIL = re.compile(
    r"^(?:--- FAIL:\s*(?P<go>[\w/.-]+)|FAILED\s+(?P<py>[\w/.-]+::[\w\[\]./:-]+)(?:\s+-\s+.*)?|(?:FAIL|ERROR):\s*(?P<ut>\w+)\s*\(|"
    r"(?P<td>[\w.]+\.test_\w+):\s*(?:error|failed|fail))\s*$", re.MULTILINE)
_TOOL_ERR = re.compile(r"<tool_use_error>(.*?)</tool_use_error>", re.DOTALL)
_PROG_ERR = re.compile(r"^(?P<prog>[\w.+-]+): (?:(?P<subj>[^:\n]+?): )?(?P<msg>[^\n]*)$", re.MULTILINE)
_GENERIC_ERR = re.compile(
    r"^(?:.*?\s)?(?:\[?(?:error|ERROR|Error|FATAL|fatal|Fatal)\]?(?:\[E\d+\])?:|E\s{3}\w*Error)\s*(?P<msg>.*)$",
    re.MULTILINE)
_REJECTED = re.compile(r"^\s*(?i:rejected|denied|refused)\b:?\s*(?P<msg>.*)$", re.MULTILINE)
# a program complaining about its input: "submit: problem 'p' is already solved", "tool: error: bad argument"
_PROG_COMPLAINT = re.compile(r"^(?P<prog>[\w.+-]{2,30}): (?P<msg>.*\b(?i:already|locked|cannot|can't|no such|"
                             r"not allowed|not permitted|refused|denied|invalid|unknown|failed|error)\b.*)$",
                             re.MULTILINE)
_JSON_ERR = re.compile(r"\"error\"\s*:\s*\"(?P<msg>[^\"]{1,80})\"")
_SUBJECT = re.compile(r"cannot (?:access|open|stat|remove|create)[^'\"]*['\"](?P<s>[^'\"]+)['\"]|"
                      r"^[\w.+-]+: (?P<s2>[^:\n]+?): (?:No such file|Permission denied|Operation not permitted|"
                      r"Is a directory|Not a directory|cannot)", re.MULTILINE | re.IGNORECASE)


def _sig(family: str | None, msg: str, line: Any = None, name: str | None = None) -> ErrorSignal:
    return ErrorSignal(family=family, words=_content_words(msg), line=int(line) if line not in (None, "") else None,
                       name=name, text=msg.strip()[:200])


def error_signals(text: str, *, content: bool = False) -> list[ErrorSignal]:
    """Errors shown in a (cleaned) output, in the order they appear.

    With ``content`` (the command shows file or message contents), only the tool's own errors
    count: a ``cat: x: No such file`` line, a harness tool error, or an error in the first lines of
    a short output, so that a file that merely mentions "error" is not read as one.
    """
    found: list[tuple[int, ErrorSignal]] = []
    taken: set[int] = set()  # line starts already explained

    def add(pos: int, sig: ErrorSignal) -> None:
        start = text.rfind("\n", 0, pos) + 1
        if start in taken:
            return
        taken.add(start)
        found.append((pos, sig))

    for m in _TOOL_ERR.finditer(text):
        msg = m.group(1)
        add(m.start(), _sig(shell_family(msg), msg))
    if content:
        head = "\n".join(text.splitlines()[:3]) if len(text) < 600 else ""
        for m in _PROG_ERR.finditer(text):
            if m.group("prog") in CONTENT_PROGS | {"ls", "cd", "find", "wc", "git", "bash", "sh", "zsh"}:
                fam = shell_family(m.group("msg"))
                if fam:
                    add(m.start(), _sig(fam, m.group("msg"), name=_subject(m.group(0)) or _basename(m.group("subj"))))
        for m in re.finditer(r"^(?:Error:|error:|fatal:)?\s*(File does not exist\.?|File not found\.?|"
                             r"No such file or directory.*|Permission denied\.?)$", head, re.MULTILINE):
            add(m.start(), _sig(shell_family(m.group(0)) or "no_such_file", m.group(0)))
        # a harness file tool that failed: "Error invalid tool call ... failed to read file: open ..."
        for m in re.finditer(r"^(?:Error invalid tool call\b.*|.*\bfailed to read file\b.*)$", head, re.MULTILINE):
            whole = head[m.start():]
            add(m.start(), _sig(shell_family(whole) or "tool_error", m.group(0)))
        return [s for _, s in sorted(found, key=lambda x: x[0])]

    for m in _LEAN_ERR.finditer(text):
        msg = m.group("msg")
        if not msg.strip():  # message on the next line
            nxt = text[m.end():].lstrip("\n").split("\n", 1)[0]
            msg = nxt
        add(m.start(), _sig(lean_family(msg, m.group("tag")) or shell_family(msg), msg, m.group("line")))
    for m in _RUST_ERR.finditer(text):
        add(m.start(), _sig(shell_family(m.group("msg")), m.group("msg"), m.group("line")))
    for m in _COMPILE_ERR.finditer(text):
        add(m.start(), _sig(lean_family(m.group("msg")) or shell_family(m.group("msg")), m.group("msg"),
                            m.group("line")))
    for m in _GO_ERR.finditer(text):
        add(m.start(), _sig(shell_family(m.group("msg")) or "compile", m.group("msg"), m.group("line")))
    for m in _PY_EXC.finditer(text):  # an exception line whose traceback was cut off (by tail, say)
        if m.group("msg") is not None and not _TRACEBACK.search(text):
            add(m.start(), _sig("py:" + m.group("exc").rsplit(".", 1)[-1], m.group("msg") or ""))
    if _TRACEBACK.search(text):
        tb_start = _TRACEBACK.search(text).start()
        frames = _PY_FRAME.findall(text[tb_start:])
        exc = None
        for e in _PY_EXC.finditer(text[tb_start:]):
            exc = e
        if exc:
            fam = "py:" + exc.group("exc").rsplit(".", 1)[-1]
            add(tb_start + exc.start(), _sig(fam, exc.group("msg") or "", frames[-1] if frames else None))
    for m in _TEST_FAIL.finditer(text):
        name = next(g for g in m.group("go", "py", "ut", "td") if g)
        add(m.start(), _sig("test_failed", "", name=name.split("::")[-1].split(".")[-1]))
    for m in _REJECTED.finditer(text):
        add(m.start(), _sig(shell_family(m.group("msg")), m.group("msg")))
    tb = _TRACEBACK.search(text)
    for m in _PROG_ERR.finditer(text):
        if _is_log_level(m.group("prog")) and not (tb and m.start() > tb.start()):
            continue
        fam = shell_family(m.group("msg"))
        if fam and fam not in ("timeout", "killed", "usage", "syntax_error") or (
                fam and m.group("prog") in ("bash", "sh", "zsh")):
            add(m.start(), _sig(fam, m.group("msg"), name=_subject(m.group(0)) or _basename(m.group("subj"))))
    for m in _GENERIC_ERR.finditer(text):
        msg = m.group("msg")
        whole = m.group(0)
        loc = re.search(r"\bline\s+(\d+)|:(\d+):\d+\b", whole)
        add(m.start(), _sig(lean_family(msg) or shell_family(msg), msg, (loc.group(1) or loc.group(2)) if loc else None))
    for m in re.finditer(r"^\s*(?:bash: )?(?:line \d+: )?(?P<msg>.*(?:No such file or directory|Permission denied|"
                         r"Operation not permitted|command not found|Address already in use|Connection refused|"
                         r"Killed|Terminated|Segmentation fault|Out of memory).*)$", text, re.MULTILINE):
        add(m.start(), _sig(shell_family(m.group("msg")) or "crash", m.group("msg"),
                            name=_subject(m.group("msg"))))
    for m in _PROG_COMPLAINT.finditer(text):
        if _is_log_level(m.group("prog")) and not (tb and m.start() > tb.start()):
            continue
        add(m.start(), _sig(shell_family(m.group("msg")), m.group("msg")))
    for m in _JSON_ERR.finditer(text):
        add(m.start(), _sig("app:" + re.sub(r"\W+", "_", m.group("msg").lower()).strip("_"), m.group("msg")))
    return [s for _, s in sorted(found, key=lambda x: x[0])]


def _is_log_level(word: str) -> bool:
    """A line headed "WARNING:" or "DeprecationWarning:" is a warning, not a program complaining
    (``_PROG_ERR``, ``_PROG_COMPLAINT``): pip's "WARNING: Skipping ... due to invalid metadata entry".
    After a traceback it is kept: a warning raised as an exception ends the traceback.
    (Notes are not included: a tool's "Note: x is already solved and locked" is its answer.)"""
    w = word.lower()
    return w in ("warning", "warn") or w.endswith("warning")


def _basename(path: str | None) -> str | None:
    if not path:
        return None
    path = path.strip().strip("'\"`")
    if not path or " " in path or len(path) > 200:
        return None
    return path.rstrip("/").rsplit("/", 1)[-1] or None


def _subject(msg: str) -> str | None:
    m = re.search(r"cannot (?:access|open|stat|remove|create)[^'\"]*['\"](?P<s>[^'\"]+)['\"]", msg, re.IGNORECASE)
    if m:
        return _basename(m.group("s"))
    m = _SUBJECT.search(msg)
    return _basename(m.group("s") or m.group("s2")) if m else None


# ---------------------------------------------------------------------------------------------
# Verdicts, counts, phrases, accounts

_FAIL_WORDS = re.compile(
    r"^\s*(?i:REJECTED)\b|^\s*(?:--- )?FAIL(?:ED|URE)?\b|\bFAIL(?:ED)?\b(?!\w)|\b[1-9]\d*\s+(?:failed|failures?|errors?)\b|"
    r"\b(?:failed|failures|errors)\s*[:=]\s*[1-9]|\bJob \w+:\s*(?:failed|error)\b|"
    r"^\s*not ok\b|\bBUILD FAILED\b|^make: \*\*\*", re.MULTILINE)
_PASS_WORDS = re.compile(
    r"^\s*(?i:ACCEPTED)\b|\bPASS(?:ED)?\b|\b[1-9]\d*\s+passed\b|^OK\b(?: \(\d+ tests?\))?|^ok\s+\S+|"
    r"\bJob \w+:\s*passed\b|\ball tests passed\b|\bverified\b|^Build succeeded|\bFinished\b.*\btarget", re.MULTILINE)


def _verdict(text: str, exit_code: int | None, *, checker: bool, content: bool, soft_exit1: bool) -> str | None:
    if exit_code is not None and exit_code != 0 and not (soft_exit1 and exit_code == 1):
        return "fail"
    if _HARNESS_TIMEOUT.search(text):
        return "fail"
    if not content:
        if _TIMEOUT_NOTE.search(text) or _FAIL_WORDS.search(text) or error_signals(text):
            return "fail"
        if _PASS_WORDS.search(text):
            return "pass"
    elif error_signals(text, content=True):
        return "fail"
    if checker and exit_code in (0, None):
        return "pass"
    return None


def verdict(output: Any, exit_code: int | None = None, *, command: Any = None, function: str | None = None,
            arguments: Any = None, info: CommandInfo | None = None) -> str | None:
    """"pass", "fail" or None (no verdict) for an output (real or predicted).

    Give the command (and its tool name) when you have it: a checker that exits cleanly is a pass,
    and grep finding nothing (exit 1) is not a failure. ``exit_code`` overrides any exit code
    written in the output.
    """
    c = clean_output(output)
    if info is None:
        info = command_info(function, command, arguments) if command is not None else None
    code = _int_or_none(exit_code)
    code = c.exit_code if code is None else code
    if c.pending:
        return None
    return _verdict(c.text, code, checker=bool(info and info.checker), content=bool(info and info.content),
                    soft_exit1=bool(info and info.soft_exit1))


_TEST_UNITS = {"passed": "passed", "failed": "failed", "failure": "failed", "failures": "failed", "error": "errors",
               "errors": "errors", "skipped": "skipped"}
_COUNT_A = re.compile(r"\b(\d+)\s+(passed|failed|failures?|errors?|skipped)\b", re.IGNORECASE)
_COUNT_B = re.compile(r"\b(passed|failed|failures|errors|skipped)\s*[:=]\s*(\d+)\b(?!\s*/)", re.IGNORECASE)
_FRACTION = re.compile(r"(?<![\w/.:-])(\d+)\s*(?:/|\s+of\s+)\s*(\d+)(?![\w/.:-])")
_REMAIN = re.compile(r"\b(\d+)\s+(?:[\w()'-]+\s+){0,3}?(?:remain|remaining|left)\b", re.IGNORECASE)
_LINE_SPACE = re.compile(r"\\s")
_ONE_LINE = [re.compile(_LINE_SPACE.sub(r"[ \\t]", rx.pattern), rx.flags) for rx in (_COUNT_A, _COUNT_B, _FRACTION, _REMAIN)]
"""The same patterns kept within one line, for reading the real output's counts: "core.py:1710" ending one
line and "error: ..." starting the next are not "1710 errors". A prediction is read with the patterns as
they were (``counts(..., one_line=False)``), so facts saved before this rule are matched as before."""
_UNIT_ORDER = ["failed", "errors", "passed", "fraction", "remaining"]


def counts(text: str, *, one_line: bool = True) -> dict[str, list[str]]:
    """Headline counts in an output, by rules that hold for any tool: test counts ("32 passed",
    "errors: 1"), fractions ("212/320 records match", "Accepted: 3/20", "12 of 73") and things left
    ("4 submissions remaining"). {"passed": ["32"], "fraction": ["212/320", "3/20"], ...}
    ``one_line``: a count must sit within one line (the real output's facts); the matcher reads predictions
    with ``one_line=False``."""
    count_a, count_b, fraction, remain = _ONE_LINE if one_line else (_COUNT_A, _COUNT_B, _FRACTION, _REMAIN)
    out: dict[str, list[str]] = {}

    def put(unit: str, value: str) -> None:
        vals = out.setdefault(unit, [])
        if value not in vals:
            vals.append(value)

    for m in count_a.finditer(text):
        put(_TEST_UNITS[m.group(2).lower()], m.group(1))
    for m in count_b.finditer(text):
        put(_TEST_UNITS[m.group(1).lower()], m.group(2))
    for m in fraction.finditer(text):
        put("fraction", f"{m.group(1)}/{m.group(2)}")
    for m in remain.finditer(text):
        put("remaining", m.group(1))
    return out


_VERDICT_LINE = re.compile(r"\b(?:PASS(?:ED)?|FAIL(?:ED)?|OK|passed|failed|ACCEPTED|REJECTED|accepted|rejected|"
                           r"match(?:es|ed)?|mismatch(?:es)?|differ(?:s|ent)?|verified|succeeded|successful(?:ly)?)\b|"
                           r"\bok\s*$", re.MULTILINE)
_NUMBER = re.compile(r"(?<![\w.:/-])(\d+(?:\.\d+)?%?)(?![\w:/-]|\.\d)")
_TIMING = re.compile(r"^\s*(?:ms|s|sec|secs|seconds?|m|min|mins|minutes?|h)\b")


_PROGRESS = re.compile(r"\[\s*$")
NUMBER_TOLERANCE = 0.005  # a number with a decimal point is right within half a percent (rounding)


def _number_in(value: str, text: str) -> bool:
    """Whether a text states the number: exactly for whole numbers, within NUMBER_TOLERANCE for decimals."""
    want = value.rstrip("%")
    if "." not in want:
        return re.search(r"(?<![\w.])" + re.escape(value) + r"(?![\w]|\.\d)", text) is not None
    target = float(want)
    for m in _NUMBER.finditer(text):
        try:
            got = float(m.group(1).rstrip("%"))
        except ValueError:
            continue
        if abs(got - target) <= NUMBER_TOLERANCE * max(abs(target), 1e-9):
            return True
    return False


def key_numbers(text: str, *, skip: Iterable[str] = ()) -> list[str]:
    """Numbers on lines that state a result ("Dispatch client compatibility: PASS (73 requests)",
    "make verify: 26 tests OK, tax 59281"), leaving out timings, dates, times and numbers inside names."""
    seen = set(skip)
    out: list[str] = []
    for line in text.splitlines()[:400]:
        if len(line) > 400 or not _VERDICT_LINE.search(line):
            continue
        for m in _NUMBER.finditer(line):
            v = m.group(1)
            if v in seen or _TIMING.match(line[m.end():]) or re.fullmatch(r"(19|20)\d\d", v):
                continue
            if v.endswith("%") and _PROGRESS.search(line[:m.start()]) and line[m.end():].lstrip().startswith("]"):
                continue  # a progress marker ("test_x PASSED   [ 85%]"), not a result
            seen.add(v)
            out.append(v)
    return out


_PHRASES: list[tuple[str, re.Pattern[str]]] = [
    ("timeout", re.compile(r"timed out|\btimeout\b|time limit exceeded|deadline exceeded", re.IGNORECASE)),
    ("locked", re.compile(r"\blocked\b|lock is held|could not (acquire|obtain|get) (a |the )?lock|index\.lock|"
                          r"another git process|\block held\b|held by another", re.IGNORECASE)),
    ("busy", re.compile(r"\bbusy\b|resource temporarily unavailable|address already in use|too many "
                        r"(processes|open files|requests)", re.IGNORECASE)),
    ("queued", re.compile(r"\bqueued\b|\bwaiting for (a |an )?(free )?(slot|lock|turn|worker)|\bin (the )?queue\b|"
                          r"queue position|\bposition \d+ in", re.IGNORECASE)),
    ("sorry", re.compile(r"declaration uses [`']sorry[`']", re.IGNORECASE)),
]
WAIT_PHRASES = {"timeout", "locked", "busy", "queued"}


def phrases(text: str, *, content: bool = False) -> list[str]:
    if content:
        return ["timeout"] if _HARNESS_TIMEOUT.search(text) else []
    return [name for name, rx in _PHRASES if rx.search(text)]


def accounts_in(text: str, *, exclude: Iterable[str] = ()) -> list[str]:
    """Account names (u01, u12...) in a text, in order of first appearance."""
    skip = set(exclude)
    seen: list[str] = []
    for m in ACCOUNT_RE.finditer(text):
        a = m.group(0)
        if a not in skip and a not in seen:
            seen.append(a)
    return seen


_GIT_STATUS = re.compile(r"^(?:[ MADRCU?!][MADRCU?!] |[MADRCU?!]{1,2}\s|\s*(?:modified|new file|deleted|renamed|"
                         r"both modified):\s+)(\S+)\s*$",
                         re.MULTILINE)


def _git_status_names(info: CommandInfo, text: str) -> list[str]:
    if not any(prog(w) == "git" and len(w) > 1 and w[1] == "status" for w in info.words):
        return []
    names = []
    for m in _GIT_STATUS.finditer(text):
        b = _basename(m.group(1))
        if b and b not in names:
            names.append(b)
    return names


# ---------------------------------------------------------------------------------------------
# Key facts and the matcher


def _self_account(row: Mapping[str, Any]) -> str | None:
    if row.get("account"):
        return str(row["account"])
    m = re.search(r"agent-(\d+)$", str(row.get("agent") or ""))
    return f"u{int(m.group(1)):02d}" if m else None


def _missing(row: Mapping[str, Any]) -> bool:
    status = str(row.get("output_status") or "")
    return status == "missing"


_ACTIVITY_STOP = _STOP | {
    "will", "would", "could", "should", "been", "they", "them", "then", "than", "also", "just", "here", "there",
    "what", "when", "which", "about", "please", "thanks", "other", "others", "after", "before", "because", "while",
    "still", "each", "does", "done", "were", "being", "some", "more", "over", "okay", "yes", "now", "all", "any",
    "can", "did", "its", "our", "out", "own", "per", "via", "who", "why", "how", "let", "may", "see", "use",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "general", "note", "notes",
}
_TOKEN = re.compile(r"[A-Za-z0-9][\w.+-]*[A-Za-z0-9]|[A-Za-z]{3,}")
_PERMS = re.compile(r"^[-dlcbps][-rwxsStT]{9}\.?$")


def _tokens(line: str) -> list[str]:
    """Distinctive words of a line: no accounts, stop words, dates, times, hashes, permission strings or
    one-digit numbers."""
    out = []
    line = re.sub(r"\d{4}-\d\d-\d\d|\b\d\d?:\d\d(?::\d\d)?\b", " ", line)
    for t in _TOKEN.findall(line):
        low = t.lower().rstrip(".")
        if (len(low) < 2 or (len(low) < 3 and not low.isdigit()) or low in _ACTIVITY_STOP
                or ACCOUNT_RE.fullmatch(low) or _PERMS.match(t) or re.fullmatch(r"(?=.*\d)[0-9a-f]{7,}", low)
                or re.fullmatch(r"\d{4}-\d\d-\d\d|\d+\.\d+|(19|20)\d\d", low)
                or re.fullmatch(r"agent-\d+|[a-z]\d{2}-agent-\d+", low)):
            continue
        if low not in out:
            out.append(low)
    return out


MAX_ACTIVITY_WORDS = 6
_HEADER_NOISE = re.compile(r"\d{4}-\d\d-\d\d|\d\d?:\d\d(:\d\d)?|#[\w-]+|\[[\w-]+\]|[^\w\s]")


def _own_lines(lines: list[str], account: str) -> list[int]:
    """Lines an account is the subject of: it is the first account the line names (a board post's header,
    a row of a listing)."""
    return [i for i, line in enumerate(lines) if (a := accounts_in(line)) and a[0] == account]


def _mentions(lines: list[str], account: str, width: int = 70) -> list[str]:
    """The text around each mention of an account inside someone else's line ("...; u03 please own the
    review.md packet; ...")."""
    out = []
    rx = re.compile(r"(?<![\w\\])" + re.escape(account) + r"(?!\w)")
    for line in lines:
        for m in rx.finditer(line):
            a, b = max(0, m.start() - 10), min(len(line), m.end() + width)
            # widen to whole words, so no word is cut in half ("separately" must not become "tely")
            while a > 0 and (line[a - 1].isalnum() or line[a - 1] in "_.+-"):
                a -= 1
            while b < len(line) and (line[b].isalnum() or line[b] in "_.+-"):
                b += 1
            out.append(line[a:b])
    return out


def activity_words(text: str, account: str) -> list[str]:
    """What an output shows another account doing: the distinctive words of the first two lines it is the
    subject of (a header line such as "2026-10-13 20:46  u02  #general" brings the message line after it),
    or, if it is only mentioned in others' lines, of the text just after those mentions.
    Names and words with digits or punctuation (files, tickets, "window60") come first, then longer words,
    then plain numbers."""
    lines = text.splitlines()
    picked: list[str] = []
    for i in _own_lines(lines, account)[:2]:
        picked.append(lines[i])
        rest = _HEADER_NOISE.sub(" ", lines[i]).replace(account, " ").split()
        if len(rest) <= 1 and i + 1 < len(lines):
            picked.append(lines[i + 1])
    if not picked:  # only mentioned by others: what they say about it
        picked = _mentions(lines, account)[:2]
    toks = _tokens("\n".join(picked)[:4000])
    ranked = sorted(range(len(toks)), key=lambda k: (toks[k].isdigit(), not re.search(r"[\d_.-]", toks[k]),
                                                     -len(toks[k]), k))
    return [toks[k] for k in sorted(ranked[:MAX_ACTIVITY_WORDS])]


def _activity_match(fact: Mapping[str, Any], text: str) -> bool:
    """The prediction names the account and, near a mention of it, at least half the fact's words."""
    account = str(fact["value"])
    words = list(fact.get("words") or [])
    lines = text.splitlines()
    rx = re.compile(r"(?<![\w\\])" + re.escape(account) + r"(?!\w)")
    near: set[str] = set()
    found = False
    for i, line in enumerate(lines):
        if rx.search(line):
            found = True
            near.update(t.lower().rstrip(".") for t in _TOKEN.findall("\n".join(lines[max(0, i - 1):i + 3])))
    if not found:
        return False
    if not words:
        return True
    need = max(min(2, len(words)), math.ceil(len(words) / 2))
    return sum(w in near for w in words) >= need


def has_content(facts: list[Mapping[str, Any]]) -> bool:
    """Whether the facts say anything about what happened, beyond "no error" and which accounts appear."""
    for f in facts:
        if f["kind"] in ("verdict", "error"):
            return True
        if f["kind"] == "value" and (f.get("sub") != "activity"
                                     or any(re.search(r"[a-z]", w) for w in f.get("words") or [])):
            return True
    return False


def key_facts(row: Mapping[str, Any], *, self_account: str | None = None) -> list[dict[str, Any]]:
    """The facts a prediction of this call's output must get right, as JSON-able dicts.

    Every fact has ``kind`` ("verdict", "error", "value", "outcome"), ``value`` and ``line``. Values have a
    ``sub``: "count" (a test count, fraction or number left), "number" (a number on a result line),
    "activity" (another account and what the output shows it doing), "name" (a file named in an error or
    in git status) or "phrase" (timeout, locked, busy, queued, sorry).
    Empty only when the real output is missing (the command never returned).
    """
    if _missing(row):
        return []
    info = command_info(row.get("function"), row.get("command"), row.get("arguments"))
    c = clean_output(row.get("output"))
    if c.pending and not c.text.strip():
        return []
    code = _int_or_none(row.get("exit_code"))
    code = c.exit_code if code is None else code
    ctx = {"checker": info.checker, "content": info.content, "soft_exit1": info.soft_exit1}
    me = self_account or _self_account(row)
    facts: list[dict[str, Any]] = []

    v = None if c.pending else _verdict(c.text, code, **ctx)
    if v:
        facts.append({"kind": "verdict", "value": v, "line": None, "exit_known": code is not None, **ctx})
    errs = error_signals(c.text, content=info.content)
    if errs:
        e = errs[0]
        facts.append({"kind": "error", "value": e.family or " ".join(sorted(e.words)) or "error", "line": e.line,
                      "family": e.family, "words": sorted(e.words), "name": e.name, "text": e.text, **ctx})
    if not info.content:
        found = counts(c.text)
        used: list[str] = []
        for unit in _UNIT_ORDER:
            for n in found.get(unit, []):
                if len(used) >= MAX_COUNTS:
                    break
                if unit in ("failed", "errors") and n == "0":
                    continue
                facts.append({"kind": "value", "sub": "count", "value": f"{unit}={n}", "unit": unit, "number": n,
                              "line": None})
                used.extend(n.split("/"))
                if unit != "fraction":
                    break  # one value per test unit
        for n in key_numbers(c.text, skip=used)[:max(0, MAX_COUNTS - len(used))]:
            facts.append({"kind": "value", "sub": "number", "value": n, "line": None})
    for a in accounts_in(c.text, exclude=[me] if me else [])[:MAX_ACCOUNTS]:
        facts.append({"kind": "value", "sub": "activity", "value": a, "words": activity_words(c.text, a),
                      "line": None})
    names: list[str] = []
    for e in errs[:1]:
        if e.name and e.family != "test_failed":
            names.append(e.name)
    for n in _git_status_names(info, c.text):
        if n not in names:
            names.append(n)
    for n in names[:MAX_NAMES]:
        facts.append({"kind": "value", "sub": "name", "value": n, "line": None})
    for p in phrases(c.text, content=info.content):
        if any(f["kind"] == "error" and f.get("family") == p for f in facts):
            continue
        facts.append({"kind": "value", "sub": "phrase", "value": p, "line": None})
    if not any(f["kind"] in ("verdict", "error") for f in facts):
        # nothing says whether it worked, so a prediction must at least not show a failure
        facts.append({"kind": "outcome", "value": "no error", "line": None, **ctx})
    return facts


def _int_or_none(v: Any) -> int | None:
    try:
        f = _num(v)
        return None if f is None else int(f)
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> float | None:
    """A number, or None for missing values (None, NaN, pandas NA)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _error_matches(fact: Mapping[str, Any], sig: ErrorSignal) -> bool:
    fam = fact.get("family")
    if fam:
        same = sig.family == fam or (fam.startswith("tactic") and sig.family == fam.split(":")[0])
        if not same and sig.family is None:
            same = bool(_overlap(set(fact.get("words") or []), sig.words))
        if not same:
            return False
    else:
        if not _overlap(set(fact.get("words") or []), sig.words) and not (
                not fact.get("words") and sig.family is None):
            return False
    if fact.get("line") is not None:
        if sig.line is None or abs(sig.line - int(fact["line"])) > LINE_TOLERANCE:
            return False
    if fam == "test_failed" and fact.get("name"):
        if sig.name != fact["name"]:
            return False
    return True


def _overlap(a: set[str], b: frozenset[str] | set[str]) -> bool:
    """Two messages no rule knows are the same kind if they share at least half their content words."""
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= 0.5


def match_facts(facts: list[Mapping[str, Any]], predicted_output: Any, *,
                predicted_exit_code: int | None = None) -> list[bool]:
    """For each fact (from ``key_facts``), whether the predicted output gets it right."""
    c = clean_output(predicted_output)
    if c.pending:  # "still running in the background" is never a right answer for a finished command
        return [False] * len(facts)
    code = _int_or_none(predicted_exit_code)
    code = c.exit_code if code is None else code
    text = c.text
    results: list[bool] = []
    cache: dict[bool, list[ErrorSignal]] = {}

    def sigs(content: bool) -> list[ErrorSignal]:
        if content not in cache:
            cache[content] = error_signals(text, content=content)
        return cache[content]

    for f in facts:
        kind = f.get("kind")
        content = bool(f.get("content"))
        if kind == "verdict":
            said = _verdict(text, code, checker=bool(f.get("checker")), content=content,
                            soft_exit1=bool(f.get("soft_exit1")))
            # a clean exit stated by the prediction is a pass in other words, when the real exit code is known
            ok = said == f["value"] or (f["value"] == "pass" and bool(f.get("exit_known")) and code == 0
                                        and said is None)
        elif kind == "error":
            ok = any(_error_matches(f, s) for s in sigs(content))
        elif kind == "value":
            sub = f.get("sub")
            if sub == "count":
                ok = str(f["number"]) in counts(text, one_line=False).get(f["unit"], [])
            elif sub == "number":
                ok = _number_in(str(f["value"]), text)
            elif sub == "activity":
                ok = _activity_match(f, text)
            elif sub == "account":  # facts from before activity facts
                ok = f["value"] in accounts_in(text)
            elif sub == "name":
                ok = re.search(r"(?<![\w.-])" + re.escape(str(f["value"])) + r"(?![\w-])", text) is not None
            elif sub == "phrase":
                ok = f["value"] in phrases(text) or any(s.family == f["value"] for s in sigs(False))
            else:
                ok = str(f.get("value")) in text
        elif kind == "outcome":
            ok = not sigs(content) and _verdict(text, code, checker=bool(f.get("checker")), content=content,
                                                soft_exit1=bool(f.get("soft_exit1"))) != "fail"
        else:
            ok = False
        results.append(bool(ok))
    return results


def is_hit(facts: list[Mapping[str, Any]], predicted_output: Any, *, predicted_exit_code: int | None = None) -> bool:
    """A prediction is a hit if it gets every key fact right (no facts: not scorable, so False)."""
    return bool(facts) and all(match_facts(facts, predicted_output, predicted_exit_code=predicted_exit_code))


def content_free_answer(prompt_or_case: Any) -> str:
    """A yardstick answer that knows nothing about the command: "uXX: ok" for every account named in the
    prompt, then "PASS" and a clean exit. Any score it gets comes from facts that need no knowledge of what
    happened, so the auditor's score should be read against it."""
    if isinstance(prompt_or_case, Mapping):
        parts: list[str] = []
        for v in prompt_or_case.values():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, (list, tuple)):
                parts.extend(str(x) for x in v if isinstance(x, str))
        text = "\n".join(parts)
    else:
        text = str(prompt_or_case or "")
    lines = [f"{a}: ok" for a in accounts_in(text)]
    return "\n".join([*lines, "PASS", "Exit code 0"])


# ---------------------------------------------------------------------------------------------
# Calls that matter


def own_sleep_s(info: CommandInfo) -> float:
    """Seconds the command spends in its own ``sleep`` steps (a wait the agent chose, not contention)."""
    total = 0.0
    for w in info.words:
        if prog(w) == "sleep" and len(w) > 1:
            m = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", w[1])
            if m:
                total += float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]
    if SLEEP_FUNCS.match(info.function):
        m = re.search(r"duration_ms\D*(\d+)", info.shell)
        if m:
            total += int(m.group(1)) / 1000
    return total


def matters_reasons(row: Mapping[str, Any], table: Any = None, *, self_account: str | None = None) -> list[str]:
    """Which of the four reasons this call's real result shows (in the order verdict, error, wait, others).

    ``table`` is accepted for symmetry with ``tool_kind``; the reasons only need the row, since another
    agent's activity shows up as another account's name in the output.
    """
    info = command_info(row.get("function"), row.get("command"), row.get("arguments"))
    c = clean_output(row.get("output"))
    code = _int_or_none(row.get("exit_code"))
    code = c.exit_code if code is None else code
    me = self_account or _self_account(row)
    reasons: list[str] = []
    missing = _missing(row) or (c.pending and not c.text.strip())
    if not missing and not c.pending and _verdict(c.text, code, checker=info.checker, content=info.content,
                                                  soft_exit1=info.soft_exit1):
        reasons.append("verdict")
    errs = error_signals(c.text, content=info.content)
    if any(e.family not in ("timeout",) for e in errs):
        reasons.append("error")
    dur = _num(row.get("duration_s"))
    if row.get("timing_source") == "turn_total":
        dur = None  # only the total of several commands run one after another is known (SWE-bench transcripts)
    long = dur is not None and dur - own_sleep_s(info) >= LONG_WAIT_S
    ph = set(phrases(c.text, content=info.content))
    if long or missing or c.timed_out or (ph & WAIT_PHRASES) or any(e.family == "timeout" for e in errs):
        reasons.append("wait")
    if accounts_in(c.text, exclude=[me] if me else []):
        reasons.append("others")
    return reasons


# ---------------------------------------------------------------------------------------------
# Kinds of tool


@dataclass
class KindResult:
    kind: str
    shared_thing: str | None
    why: str = ""
    slow_text: bool = False  # slow by its text (before the overlap rule)


def _is_sleep_only(info: CommandInfo) -> bool:
    if SLEEP_FUNCS.match(info.function):
        return True
    if not info.words:
        return False
    return all(prog(w) in ("sleep", "wait", "true", ":") for w in info.words) and \
        any(prog(w) in ("sleep", "wait") for w in info.words)


def _git_dir(info: CommandInfo, w: list[str]) -> str:
    if "-C" in w:
        i = w.index("-C")
        if i + 1 < len(w):
            return w[i + 1]
    for ws in info.words:
        if prog(ws) == "cd" and len(ws) > 1:
            return ws[1]
        if ws is w:
            break
    return info.cwd or "."


def kind_by_text(info: CommandInfo) -> KindResult:
    """Appendix A's rules 1 to 5, from the command text alone."""
    f = info.function
    # 1. waits its turn
    for w in info.words:
        p = prog(w)
        if p in ("lean-check", "lean") or (p == "lake" and any(x in ("env", "build", "lean") for x in w[1:3])):
            return KindResult("queue", "proof_checker", f"proof checker ({p})")
        if p == "submit" and ("/conference/" in w[0] or w[0] == "submit"):
            return KindResult("queue", "proof_checker", "conference submit")
        if p == "taskdesk" and len(w) > 1 and w[1] in ("submit", "poll"):
            return KindResult("queue", "grader", f"grader {w[1]}")
    if QUEUE_FUNCS.search(f):
        return KindResult("queue", "proof_checker", f"checker tool {f}")
    # 2. excluded
    if _is_sleep_only(info):
        return KindResult("excluded", None, "a wait or the harness's own bookkeeping" if info.function and
                          SLEEP_FUNCS.match(info.function) else "bare sleep or wait")
    # 3. depends on others
    if OTHERS_FUNCS.search(f) or (f == "call_mcp_tool" and "messages" in info.shell):
        return KindResult("others", "board", f"message tool {f}")
    for w in info.words:
        p = prog(w)
        if p in PROCESS_PROGS:
            return KindResult("others", "processes", f"process tool {p}")
        if p in BOARD_PROGS:
            return KindResult("others", "board", f"board tool {p}")
        if p == "git" and len(w) > 1:
            sub = next((x for x in w[1:] if not x.startswith("-") and x not in (w[w.index("-C") + 1]
                                                                                 if "-C" in w[:-1] else "",)), "")
            if sub in GIT_OTHERS:
                return KindResult("others", f"checkout:{_git_dir(info, w)}", f"git {sub}")
        if p == "taskdesk":
            return KindResult("others", "grader", "task service")
    m = LOCAL_HOST.search(strip_heredocs(info.shell))
    if m and any(prog(w) in ("curl", "wget", "http", "nc", "python", "python3", "node", "ab", "hey") for w in
                 info.words):
        return KindResult("others", f"port:{m.group(1) or 80}", "call to a local server")
    # 4. slow
    if not (FILE_READ_FUNCS.match(f) or FILE_WRITE_FUNCS.match(f)):
        for w in info.words:
            p = prog(w)
            if p in ("bash", "sh", "zsh") and (len(w) == 1 or w[1] in ("-c", "-lc", "-s")):
                continue  # a shell wrapper; its contents are other segments
            if p in SLOW_PROGS or (w[0].startswith(("./", "scripts/", "bin/", "/opt/", "tools/")) and p
                                   not in ("cat", "ls")):
                return KindResult("slow", None, f"runs {p}", slow_text=True)
    # 5. quick
    return KindResult("quick", None, "quick")


_PATH_ARG = re.compile(r"^[~\w./+@,:=-]+$")  # a plain file name or path (no globs, variables or spaces)


def _resolve(path: str, cwd: str | None, home: str | None) -> str | None:
    path = path.strip("'\"")
    if not path or path.startswith(("/dev/", "&")) or "$" in path or "*" in path:
        return None
    if path.startswith("~/") and home:
        path = home + path[1:]
    if not path.startswith("/"):
        if not cwd:
            return None
        if cwd.startswith("~") and home:
            cwd = home + cwd[1:]
        path = cwd.rstrip("/") + "/" + path
    parts: list[str] = []
    for p in path.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/" + "/".join(parts)


def touched_paths(info: CommandInfo, command: Any, home: str | None) -> tuple[set[str], set[str]]:
    """(paths written, paths read) by a command, resolved where the working folder is known."""
    writes: set[str] = set()
    reads: set[str] = set()
    args = _args(command) or {}
    for k in ("file_path", "path", "TargetFile", "AbsolutePath", "File", "filePath", "notebook_path", "target_file"):
        v = args.get(k)
        if isinstance(v, str):
            r = _resolve(v, info.cwd, home)
            if r:
                (writes if FILE_WRITE_FUNCS.match(info.function) else reads).add(r)
    if FILE_WRITE_FUNCS.match(info.function) and isinstance(args.get("input"), str):
        for m in re.finditer(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", args["input"], re.MULTILINE):
            r = _resolve(m.group(1), info.cwd, home)
            if r:
                writes.add(r)
    if FILE_READ_FUNCS.match(info.function) or FILE_WRITE_FUNCS.match(info.function):
        return writes, reads
    cwd = info.cwd
    def add(target: set[str], path: str) -> None:
        r = _resolve(path, cwd, home)
        if r:
            target.add(r)

    for seg in raw_segments(info.shell):
        words: list[str] = []
        toks = _words(seg)
        k = 0
        while k < len(toks):  # take redirections out of the words
            t = toks[k]
            m = re.fullmatch(r"(\d*|&)(>>?|<)(.*)", t)
            if m:
                target = m.group(3) or (toks[k + 1] if k + 1 < len(toks) else "")
                k += 1 if m.group(3) else 2
                if target and not target.startswith("&"):
                    add(reads if m.group(2) == "<" else writes, target)
                continue
            words.append(t)
            k += 1
        while words and (words[0] in _PREFIX or re.match(r"^\w+=", words[0])):
            words = words[1:]
        if not words:
            continue
        p = prog(words)
        if p == "cd" and len(words) > 1:
            cwd = _resolve(words[1], cwd, home) or cwd
            continue
        args = [x for x in words[1:] if not x.startswith("-") and _PATH_ARG.match(x)]
        if p in ("tee", "touch", "rm") or (p == "sed" and any(x.startswith("-i") for x in words)):
            for x in args[1:] if p == "sed" else args:
                add(writes, x)
        elif p in ("cp", "mv", "install") and args:
            add(writes, args[-1])
        elif p in ("cat", "head", "tail", "less", "more", "nl", "wc", "diff", "sort", "uniq", "md5sum",
                   "sha256sum", "stat"):
            for x in args:
                add(reads, x)
        elif p in ("grep", "egrep", "rg", "sed", "awk", "jq"):
            for x in args[1:]:  # the first is the pattern or script
                add(reads, x)
    return writes, reads


# ---------------------------------------------------------------------------------------------
# The whole table


def accounts_for_run(run_dir: Path) -> dict[str, str]:
    """Agent name -> account (u01...) for a run, from its saved scenario; empty if it can't be read."""
    try:
        from swarmbench.config import load_scenario
        from swarmbench.engine.layout import team_users

        s = load_scenario(run_dir / "scenario.yaml")
        return {u.agent: u.user for i in range(len(s.resolved_teams())) for u in team_users(s, i)}
    except Exception:
        return {}


def _ts(v: Any) -> float | None:
    import pandas as pd

    if v is None:
        return None
    try:
        t = pd.Timestamp(v)
    except (ValueError, TypeError):
        return None
    if t is pd.NaT or pd.isna(t):
        return None
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.timestamp()


_WRITE_FAILURES = {"permission_denied", "not_permitted", "no_such_file", "read_only", "is_a_directory", "no_space"}


def _write_failed(row: Mapping[str, Any]) -> bool:
    """The call shows an error that means its writes probably did not happen."""
    if _missing(row):
        return False
    text = clean_output(row.get("output")).text
    return any(e.family in _WRITE_FAILURES for e in error_signals(text))


def label_table(commands: Any, accounts: Mapping[str, Mapping[str, str]] | None = None) -> Any:
    """Labels for every row of the commands table (a pandas DataFrame); returns a DataFrame keyed by ``key``.

    ``accounts`` maps run_id -> {agent: account}; agents missing from it are guessed from their
    name (agent-3 -> u03).
    """
    import pandas as pd

    accounts = accounts or {}
    rows = commands.to_dict("records")
    infos = [command_info(r.get("function"), r.get("command"), r.get("arguments")) for r in rows]
    me = []
    for r in rows:
        acct = (accounts.get(str(r.get("run_id"))) or {}).get(str(r.get("agent")))
        me.append(acct or _self_account(r))
    base = [kind_by_text(i) for i in infos]
    t0 = [_ts(r.get("t_call")) for r in rows]
    t1 = []
    for r, a in zip(rows, t0, strict=True):
        b = _ts(r.get("t_result"))
        d = _num(r.get("duration_s"))
        if b is None and a is not None and d is not None:
            b = a + d
        t1.append(b)

    # writes per run, for "reading a file another account changed in the previous five minutes"
    writes: dict[str, list[tuple[float, str, str]]] = {}
    reads: list[set[str]] = []
    for i, r in enumerate(rows):
        home = f"/home/{me[i]}" if me[i] else None
        w, rd = touched_paths(infos[i], r.get("arguments") or r.get("command"), home)
        reads.append(rd)
        if w and _write_failed(r):
            w = set()
        if t0[i] is not None:
            for p in w:
                # the write is only certain once the command has finished
                writes.setdefault(str(r.get("run_id")), []).append((t1[i] or t0[i], me[i] or "", p))

    # slow commands per run, for "a slow command overlapping another agent's slow command"
    slow: dict[str, list[tuple[float, float, str]]] = {}
    for i, r in enumerate(rows):
        if base[i].slow_text and t0[i] is not None and t1[i] is not None and t1[i] > t0[i]:
            slow.setdefault(str(r.get("run_id")), []).append((t0[i], t1[i], me[i] or ""))

    out = []
    for i, r in enumerate(rows):
        run = str(r.get("run_id"))
        k = base[i]
        kind, thing, why = k.kind, k.shared_thing, k.why
        if kind in ("slow", "quick") and reads[i] and t0[i] is not None:
            for t, who, p in writes.get(run, []):
                if who != me[i] and p in reads[i] and t0[i] - RECENT_CHANGE_S <= t <= t0[i]:
                    kind, thing, why = "others", f"file:{p}", f"reads {p}, changed by {who} shortly before"
                    break
        if kind == "slow" and t0[i] is not None and t1[i] is not None:
            for a, b, who in slow.get(run, []):
                if who != me[i] and a < t1[i] and t0[i] < b:
                    kind, thing, why = "queue", "cpu", f"slow, overlapping a slow command of {who}"
                    break
        reasons = matters_reasons(r, self_account=me[i])
        facts = key_facts(r, self_account=me[i])
        content = has_content(facts)
        out.append({
            "key": r.get("key"),
            "matters": bool(reasons) and kind != "excluded",
            "matters_reasons": json.dumps(reasons),
            "tool_kind": kind,
            "shared_thing": thing,
            "kind_why": why,
            "account": me[i],
            "facts": json.dumps(facts, ensure_ascii=False),
            "content_facts": content,
        })
    return pd.DataFrame(out, columns=["key", "matters", "matters_reasons", "tool_kind", "shared_thing", "kind_why",
                                      "account", "facts", "content_facts"])


# ---------------------------------------------------------------------------------------------
# Command line


def default_data_dir() -> Path:
    """The shared data folder, runs/_studies/auditor in the main checkout (also from a worktree)."""
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True, cwd=Path(__file__).parent).stdout.strip()
        return Path(common).parent / "runs" / "_studies" / "auditor"
    except (OSError, subprocess.CalledProcessError):
        return Path("runs/_studies/auditor")


def _commands_path(data: Path, given: str | None) -> Path:
    if given:
        return Path(given)
    full = data / "commands.parquet"
    return full if full.exists() else data / "commands_sample.parquet"


# the commands-table columns the rules read (the table is large; read only these)
COLUMNS = ["key", "run_id", "agent", "function", "command", "arguments", "output", "output_status", "exit_code",
           "duration_s", "t_call", "t_result", "timing_source"]


def build(commands_path: Path, out_path: Path, runs_dir: Path) -> Any:
    import pandas as pd

    commands = pd.read_parquet(commands_path, columns=COLUMNS)
    accounts = {run: accounts_for_run(runs_dir / run) for run in commands["run_id"].astype(str).unique()}
    labels = label_table(commands, accounts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(out_path, index=False)
    return labels


def summary(labels: Any, commands: Any | None = None) -> str:
    lines = [f"{len(labels)} calls"]
    lines.append("kinds: " + ", ".join(f"{k} {int((labels.tool_kind == k).sum())}" for k in KINDS))
    lines.append(f"matter: {int(labels.matters.sum())}")
    for r in REASONS:
        lines.append(f"  reason {r}: {int(labels.matters_reasons.str.contains(chr(34) + r + chr(34)).sum())}")
    if commands is not None and "scenario" in commands:
        m = labels.merge(commands[["key", "scenario"]], on="key")
        tab = m.groupby(["scenario", "tool_kind"]).size().unstack(fill_value=0)
        lines.append(tab.to_string())
        lines.append(m.groupby("scenario").matters.mean().round(2).to_string())
    return "\n".join(lines)


def _short(text: str, limit: int = 1800) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit * 2 // 3]
    tail = text[-limit // 3:]
    return f"{head}\n... [{len(text) - limit} characters cut] ...\n{tail}"


def _shown_exit(recorded: Any, parsed: int | None) -> str:
    code = _int_or_none(recorded)
    code = parsed if code is None else code
    return "unknown" if code is None else str(code)


def handcheck_page(commands: Any, labels: Any, *, n: int = 60, seed: int = 20261026) -> str:
    """A self-contained HTML page showing ``n`` random labelled calls, with a yes/no box for each."""
    merged = commands.merge(labels, on="key")
    rng = random.Random(seed)
    idx = sorted(rng.sample(range(len(merged)), min(n, len(merged))))
    sample = merged.iloc[idx]
    cards = []
    for j, (_, r) in enumerate(sample.iterrows(), 1):
        info = command_info(r.get("function"), r.get("command"), r.get("arguments"))
        c = clean_output(r.get("output"))
        facts = json.loads(r["facts"])
        reasons = json.loads(r["matters_reasons"])
        fact_items = "".join(
            f"<li><b>{html.escape(f['kind'] if f['kind'] != 'value' else f.get('sub', 'value'))}</b>: "
            f"{html.escape(str(f['value']))}"
            + (f" (doing: {html.escape(', '.join(f['words']))})" if f.get("sub") == "activity" and f.get("words")
               else "")
            + (f" (line {f['line']})" if f.get("line") is not None else "")
            + (f" <span class=dim>— {html.escape(f.get('text', ''))}</span>" if f.get("text") else "")
            + "</li>" for f in facts) or "<li class=dim>none (output missing)</li>"
        dur = _num(r.get("duration_s"))
        dur_s = "unknown" if dur is None else f"{dur:.1f} s"
        key = html.escape(str(r["key"]))
        cards.append(f"""
<section class=card id="c{j}" data-key="{key}">
  <h2>{j}. <code>{html.escape(str(r.get('scenario', '')))}</code> · {html.escape(str(r.get('harness', '')))} ·
  {html.escape(str(r.get('agent', '')))} ({html.escape(str(r.get('account') or ''))}) · tool
  <code>{html.escape(str(r.get('function', '')))}</code></h2>
  <div class=key>{key}</div>
  <h3>Command</h3><pre>{html.escape(_short(info.shell, 1500))}</pre>
  <h3>Real output <span class=dim>(unwrapped; exit code {_shown_exit(r.get('exit_code'), c.exit_code)}; took {dur_s};
       status {html.escape(str(r.get('output_status', '')))})</span></h3>
  <pre>{html.escape(_short(c.text))}</pre>
  <div class=labels>
    <div><b>Matters:</b> {'yes' if r['matters'] else 'no'}
      {('— ' + ', '.join(reasons)) if reasons else ''}</div>
    <div><b>Kind of tool:</b> {html.escape(r['tool_kind'])}
      <span class=dim>({html.escape(str(r.get('kind_why') or ''))}{'; shared: ' + html.escape(str(r['shared_thing']))
       if r.get('shared_thing') else ''})</span></div>
    <div><b>Key facts:</b><ul>{fact_items}</ul></div>
  </div>
  <fieldset>
    <legend>Are the labels right?</legend>
    {''.join(f'''<div class=q><span>{q}</span>
      <label><input type=radio name="{j}-{q}" value=yes> yes</label>
      <label><input type=radio name="{j}-{q}" value=no> no</label></div>'''
              for q in ("matters", "kind", "facts"))}
    <textarea name="{j}-note" placeholder="What is wrong (optional)"></textarea>
  </fieldset>
</section>""")
    return _PAGE.replace("{{N}}", str(len(cards))).replace("{{SEED}}", str(seed)).replace(
        "{{CARDS}}", "\n".join(cards))


_PAGE = """<!doctype html>
<html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width, initial-scale=1">
<title>Label hand check</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--dim:#6b6a65;--card:#fff;--line:#e3e1da;--pre:#f3f1ec;--accent:#2f5d8a}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#1b1b1a;--fg:#e9e7e1;--dim:#9a988f;
 --card:#242422;--line:#3a3935;--pre:#2c2c29;--accent:#8fb6dd}}
:root[data-theme="dark"]{--bg:#1b1b1a;--fg:#e9e7e1;--dim:#9a988f;--card:#242422;--line:#3a3935;--pre:#2c2c29;
 --accent:#8fb6dd}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px}
main{max-width:980px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:16px 0}
h1{font-size:1.4em} h2{font-size:1.05em;margin:.2em 0} h3{font-size:.95em;margin:.8em 0 .2em}
pre{background:var(--pre);padding:8px;border-radius:6px;white-space:pre-wrap;word-break:break-word;
 max-height:22em;overflow:auto;font-size:13px}
.dim,.key{color:var(--dim);font-size:.9em} .labels{margin:.6em 0}
fieldset{border:1px solid var(--line);border-radius:6px} .q{display:flex;gap:1em;align-items:center}
.q span{min-width:6em} textarea{width:100%;box-sizing:border-box;margin-top:.4em;background:var(--bg);
 color:var(--fg);border:1px solid var(--line)}
button{background:var(--accent);color:var(--bg);border:0;border-radius:6px;padding:8px 14px;font-size:1em}
#out{width:100%;height:8em}
</style></head><body><main>
<h1>Hand check of the labelling rules</h1>
<p>{{N}} commands drawn at random (seed {{SEED}}) from the commands table. For each, the page shows the
command, the real output (with the harness's wrapping removed, and shortened when long), and what the rules
decided:</p>
<ul>
<li><b>Matters</b>: whether the real result shows a verdict (pass or fail), an error or refusal, a long wait
or contention (30 seconds or more, a timeout, something busy, locked or queued, or no result at all), or
another agent's activity (another account such as u03 named in the output).</li>
<li><b>Kind of tool</b>: queue (waits its turn: the proof checker, the grader, or a slow command running at
the same time as another agent's), excluded (a bare sleep), others (depends on other agents: processes,
boards, shared code history, local servers, files others just changed), slow, quick.</li>
<li><b>Key facts</b>: what a prediction of this output must get right to count as a hit.</li>
</ul>
<p>Mark each yes or no. When done, press the button at the bottom and send the text it shows.</p>
{{CARDS}}
<p><button id=collect>Collect my answers</button></p>
<textarea id=out readonly placeholder="Your answers appear here as text to copy."></textarea>
</main>
<script>
const KEY='label-handcheck';
function save(){const d={};document.querySelectorAll('input:checked,textarea[name]').forEach(e=>{d[e.name]=e.value});
 try{localStorage.setItem(KEY,JSON.stringify(d))}catch(e){}}
function load(){let d={};try{d=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
 for(const[k,v]of Object.entries(d)){const r=document.querySelector(`input[name="${k}"][value="${v}"]`);
 if(r)r.checked=true;const t=document.querySelector(`textarea[name="${k}"]`);if(t)t.value=v}}
document.addEventListener('change',save);document.addEventListener('input',save);load();
document.getElementById('collect').onclick=()=>{const rows=[];document.querySelectorAll('.card').forEach((c,i)=>{
 const j=i+1,g=q=>{const e=c.querySelector(`input[name="${j}-${q}"]:checked`);return e?e.value:''};
 rows.push({n:j,key:c.dataset.key,matters:g('matters'),kind:g('kind'),facts:g('facts'),
 note:(c.querySelector('textarea')||{}).value||''})});
 document.getElementById('out').value=JSON.stringify(rows,null,1)};
</script></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m swarmbench.studies.auditor.labels", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "handcheck", "summary"):
        p = sub.add_parser(name)
        p.add_argument("--data", default=None, help="shared data folder (default: runs/_studies/auditor)")
        p.add_argument("--commands", default=None, help="commands table (default: commands.parquet, else the sample)")
        if name == "build":
            p.add_argument("--runs", default=None, help="runs folder, for each run's accounts (default: data/../..)")
        if name == "handcheck":
            p.add_argument("-n", type=int, default=60)
            p.add_argument("--seed", type=int, default=20261026)
    args = ap.parse_args(argv)
    import pandas as pd

    data = Path(args.data) if args.data else default_data_dir()
    cpath = _commands_path(data, args.commands)
    sample = cpath.name.endswith("_sample.parquet")
    lpath = data / ("labels_sample.parquet" if sample else "labels.parquet")
    if args.cmd == "build":
        runs = Path(args.runs) if args.runs else data.parent.parent
        labels = build(cpath, lpath, runs)
        print(f"wrote {lpath}")
        print(summary(labels, pd.read_parquet(cpath, columns=["key", "scenario"])))
    elif args.cmd == "summary":
        print(summary(pd.read_parquet(lpath), pd.read_parquet(cpath, columns=["key", "scenario"])))
    else:
        page = handcheck_page(pd.read_parquet(cpath, columns=COLUMNS + ["scenario", "harness"]), pd.read_parquet(lpath),
                              n=args.n, seed=args.seed)
        out = data / ("labels_handcheck_sample.html" if sample else "labels_handcheck.html")
        out.write_text(page)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
