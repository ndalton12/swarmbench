"""Reading and comparing an agent's next action (the agent-reaction test's rules, fixed before any call).

The reaction test (``reaction.py``) gets three next actions for each case: **A**, what the agent's model
does after seeing the auditor's predicted output; **R**, what it does after seeing the real output again
(a fresh sample of the same request); and **L**, what it really did (the logged answer). Each is the
model's answer to the agent's next request. This module turns an answer into a **category** and a
**target** by fixed rules, with no model judging, and compares two of them.

Rules
-----

1. **Which call.** The action is the answer's first tool call. An answer without a tool call is
   ``stop`` (the model only wrote text, or ended its turn).

2. **Steps.** A tool call becomes a list of steps.

   - A shell call (Claude Code ``Bash``, Antigravity ``run_command``) gives one step per simple command
     in its shell text: the text is split at ``;``, ``|``, ``&&``, ``||``, ``&``, parentheses and
     newlines outside quotes, heredoc bodies are left out, and leading wrappers (``sudo``, ``timeout
     N``, ``env X=1``, ...) are dropped (the auditor study's own shell reading, ``labels.segments``).
     Bookkeeping gives no step: ``cd``, ``echo``/``printf`` without a redirect, ``export``, ``set``,
     ``true``, ``pwd``, ``date``, ``mktemp``, shell syntax (``for``, ``done``, ``[``, ``test``, ``fi``,
     ...; the full list is ``TRIVIAL``) and comments.
   - A Codex ``exec`` call runs JavaScript that calls tools: each ``tools.exec_command({cmd: ...})``
     gives the steps of its shell text, each ``tools.apply_patch(...)`` an ``edit`` step on the files it
     names, ``tools.write_stdin`` with no input a ``wait`` step (it reads a running command's output),
     with input a ``run`` step; any other ``tools.X`` call is read as a tool named X (below). Only
     calls in the code count: text inside strings, template literals, comments and regular-expression
     literals is not searched.
   - Any other tool gives one step, by its name (the table under rule 3).

3. **Categories of a step.**

   - ``submit`` (submit or declare done): the programs ``submit``, ``submit-plan``, ``rl-submit``,
     ``lean-submit``, ``taskdesk submit``; tools named ``ReportFindings``, ``submit*``.
   - ``message`` (message another agent or post): a board-like program (``board``, ``bulletin``,
     ``msg``, ``mail``, ``message``, ``messages``, ``wall``, ``post``, ``inbox``, ``swarm-msg``) with a
     posting subcommand (``post``, ``send``, ``write``, ``reply``, ``msg``, ``dm``) or a ``-m``
     option; tools that send (``SendMessage``, ``send_message``, ``send_direct_message``,
     ``post_intent``, ``mcp__messages__send_message``; ``call_mcp_tool`` naming such a tool).
   - ``run`` (run a check, test or program): any program not listed under another category, e.g.
     ``lean-check``, ``pytest``, ``make``, ``python3``, ``node``, a scenario's own tools.
   - ``edit`` (write or change files or the repository): an output redirect to a file (``>``,
     ``>>``; not ``/dev/null``), ``tee``, ``sed -i``, ``cp``, ``mv``, ``rm``, ``touch``, ``mkdir``,
     ``ln``, ``chmod``, ``patch``, ``truncate``; ``git`` with ``add``, ``commit``, ``checkout``,
     ``switch``, ``reset``, ``restore``, ``merge``, ``rebase``, ``stash``, ``apply``,
     ``cherry-pick``, ``am``, ``push``, ``pull``, ``rm``, ``mv``, ``tag``, ``init``, ``clone``;
     file-writing tools (``Write``, ``Edit``, ``MultiEdit``, ``NotebookEdit``, ``write_to_file``,
     ``replace_file_content``, ``multi_replace_file_content``, ``apply_patch``, ``edit_file``,
     ``create_file``). A redirect into a file makes a command an ``edit`` step when its program only
     prints or reads (``cat > f <<EOF``, ``echo x > f``, ``grep ... > f``); a program that runs
     (``python3 x.py > log``) stays a ``run`` step.
   - ``wait`` (wait, sleep or poll): ``sleep``, ``wait``, ``tail -f``; tools ``sleep``, ``wait``,
     ``wait_agent``, ``ScheduleWakeup``, ``CronCreate``, ``TaskOutput``, ``BashOutput``,
     ``command_status``, ``schedule``, ``manage_task``.
   - ``read`` (read or inspect): ``cat``, ``head``, ``tail``, ``less``, ``grep``, ``rg``, ``sed``
     (without ``-i``), ``awk``, ``jq``, ``diff``, ``ls``, ``find``, ``wc``, ``stat``, ``du``,
     ``df``, ``tree``, ``ps``, ``pgrep``, ``top``, ``who``, ``id``, ``which``, ``env``... (the auditor
     study's lists of content, inspection and process programs); ``git`` with ``status``, ``log``,
     ``diff``, ``show``, ``blame``, ``branch``, ``ls-files``, ``rev-parse``, ``remote``,
     ``shortlog``, ``reflog``, ``grep``, ``fetch``; a board-like program without a posting subcommand
     (``board read``), ``problems``, ``list_users``; reading tools (``Read``, ``Glob``, ``Grep``,
     ``LS``, ``view_file``, ``view_file_outline``, ``view_code_item``, ``list_dir``,
     ``grep_search``, ``find_by_name``, ``codebase_search``, ``read_resource``, ``list_resources``,
     ``get_messages``, ``get_bulletin_board``, ``mcp__messages__check_messages``,
     ``mcp__messages__list_users``, ``ListAgents``, ``list_agents``, ``TaskList``, ``TaskGet``,
     ``CronList``).
   - ``other``: any other tool (``Agent``, ``spawn_agent``, ``TaskStop``, ``Skill``, ...).

4. **One category per call.** A call's category is its highest-ranked step category:
   ``submit`` > ``message`` > ``run`` > ``edit`` > ``wait`` > ``read`` > ``other``. A call whose
   steps are all bookkeeping is ``other``.

5. **Re-run.** If the call is the same command as the target call (the one whose result was swapped):
   the same shell text, or for a non-shell tool the same tool with the same arguments, compared with
   runs of whitespace made one space and the agent's own labels (Antigravity's ``toolAction``,
   ``toolSummary``; a ``description``) left out, its category is ``rerun`` instead.

6. **Target.** Taken from the first step of the call's category.

   - ``read`` and ``edit``: the file names involved (the last part of each path: a tool's path
     argument, a redirect's file, the program's path-like arguments), sorted and joined; when there
     are none, the program (with its subcommand for ``git``, a board-like program or ``taskdesk``).
   - ``run`` and ``submit``: the program (with its subcommand, as above) and the last part of each
     path-like argument, in order; options and the text of heredocs are left out.
   - ``message``: who it goes to (a channel or a recipient: the subcommand's first argument, or a tool's
     ``to``/``recipient``/``channel`` argument), else the program or tool.
   - ``wait``, ``rerun``, ``stop``: no target (the category says it all).
   - ``other``: the tool's name.

7. **Same action.** Two actions are the same (**strict**) when category and target are both equal; the
   looser measure needs the same category only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

CATEGORIES = ("rerun", "submit", "message", "run", "edit", "wait", "read", "other", "stop")
CATEGORY_NAMES = {
    "rerun": "re-run the same command",
    "submit": "submit or declare done",
    "message": "message another agent or post",
    "run": "run a check, test or program",
    "edit": "edit or write a file",
    "wait": "wait, sleep or poll",
    "read": "read or inspect",
    "other": "other tool",
    "stop": "text only or stop",
}
RANK = ("submit", "message", "run", "edit", "wait", "read", "other")

SUBMIT_PROGS = {"submit", "submit-plan", "rl-submit", "lean-submit"}
BOARD_PROGS = {"board", "bulletin", "msg", "mail", "message", "messages", "wall", "post", "inbox", "swarm-msg"}
POST_SUBCOMMANDS = {"post", "send", "write", "reply", "msg", "dm"}
TRIVIAL = {"cd", "echo", "printf", "export", "set", "true", "false", "pwd", "date", "clear", ":", "unset", "source",
           ".", "mktemp", "for", "done", "fi", "esac", "case", "select", "in", "[", "[[", "test", "let", "local",
           "declare", "read", "shift", "return", "exit", "break", "continue", "trap", "umask", "ulimit", "alias"}
EDIT_PROGS = {"tee", "cp", "mv", "rm", "touch", "mkdir", "ln", "chmod", "patch", "truncate", "rmdir", "install"}
GIT_EDIT = {"add", "commit", "checkout", "switch", "reset", "restore", "merge", "rebase", "stash", "apply",
            "cherry-pick", "am", "push", "pull", "rm", "mv", "tag", "init", "clone"}
GIT_READ = {"status", "log", "diff", "show", "blame", "branch", "ls-files", "rev-parse", "remote", "shortlog",
            "reflog", "grep", "fetch", "describe", "cat-file", "ls-tree", "config"}
WAIT_PROGS = {"sleep", "wait"}
READ_EXTRA = {"problems", "list_users", "less", "more", "bat", "tac", "strings", "xxd", "od", "file", "realpath",
              "readlink", "basename", "dirname", "column", "cut", "sort", "uniq", "tr", "printenv", "hostname",
              "uptime", "free", "nproc", "lsof", "ss", "netstat", "pstree", "w", "users", "last", "fuser", "atop",
              "htop", "top", "loginctl", "md5sum", "sha256sum", "sha1sum", "cmp"}

SUBMIT_TOOLS = re.compile(r"^(ReportFindings|submit\w*)$", re.IGNORECASE)
MESSAGE_TOOLS = re.compile(r"^(SendMessage|send_message|send_direct_message|post_intent|mcp__\w+__send_\w+|"
                           r"mcp__\w+__post\w*)$", re.IGNORECASE)
WAIT_TOOLS = re.compile(r"^(sleep|wait|wait_agent|ScheduleWakeup|CronCreate|TaskOutput|BashOutput|command_status|"
                        r"schedule|manage_task)$", re.IGNORECASE)
READ_TOOLS = re.compile(r"^(Read|Glob|Grep|LS|view_file|view_file_outline|view_code_item|list_dir|grep_search|"
                        r"find_by_name|codebase_search|read_resource|list_resources|get_messages|get_bulletin_board|"
                        r"mcp__\w+__(check|list|get|read)\w*|ListAgents|list_agents|TaskList|TaskGet|CronList|"
                        r"read_file|cat_file|NotebookRead)$", re.IGNORECASE)
EDIT_TOOLS = re.compile(r"^(Write|Edit|MultiEdit|NotebookEdit|write_to_file|replace_file_content|"
                        r"multi_replace_file_content|apply_patch|edit_file|create_file)$", re.IGNORECASE)
SHELL_TOOLS = {"Bash": "command", "bash": "command", "run_command": "CommandLine", "shell": "command",
               "exec_command": "cmd", "local_shell": "command"}
PATH_KEYS = ("file_path", "path", "TargetFile", "AbsolutePath", "File", "filePath", "notebook_path", "target_file",
             "DirectoryPath", "SearchPath", "SearchDirectory", "pattern")
RECIPIENT_KEYS = ("to", "recipient", "recipients", "channel", "target", "user", "agent", "Recipient", "To")
LABEL_KEYS = {"toolAction", "toolSummary", "description", "Description"}


@dataclass
class Step:
    category: str
    target: str = ""


@dataclass
class Action:
    category: str
    target: str = ""
    steps: list[Step] = field(default_factory=list)
    calls: int = 0
    """How many tool calls the answer made (the action is read from the first)."""
    text: str = ""
    """The call, shortened, for reading the results."""

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "target": self.target, "calls": self.calls, "text": self.text,
                "steps": [[s.category, s.target] for s in self.steps]}


# --- helpers ------------------------------------------------------------------------------------------------


def _base(path: str) -> str:
    p = path.strip().strip("'\"").rstrip("/")
    return p.rsplit("/", 1)[-1] if p else ""


_PATHLIKE = re.compile(r"^[~\w./+@,:=-]*[./][~\w./+@,:=-]*$")


def _is_path(word: str) -> bool:
    return bool(_PATHLIKE.match(word)) and not word.startswith("-") and not re.fullmatch(r"[\d.]+", word)


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _prog(words: list[str]) -> str:
    return words[0].rsplit("/", 1)[-1].strip("'\"") if words else ""


def _subcommand(words: list[str]) -> str | None:
    for w in words[1:]:
        if not w.startswith("-"):
            return w
    return None


def _program_label(words: list[str]) -> str:
    p = _prog(words)
    if p in ("git", "taskdesk") or p in BOARD_PROGS:
        sub = _subcommand(words)
        return f"{p} {sub}" if sub else p
    return p


def _redirect_targets(seg: str) -> tuple[list[str], list[str]]:
    """(the words of a simple command without its redirections, the files it writes by redirection)."""
    from swarmbench.studies.auditor.labels import _words

    toks = _words(seg)
    words: list[str] = []
    writes: list[str] = []
    k = 0
    while k < len(toks):
        t = toks[k]
        m = re.fullmatch(r"(\d*|&)(>>?|<)(.*)", t)
        if m:
            target = m.group(3) or (toks[k + 1] if k + 1 < len(toks) else "")
            k += 1 if m.group(3) else 2
            if m.group(2) != "<" and target and not target.startswith("&") and target != "/dev/null":
                writes.append(target)
            continue
        words.append(t)
        k += 1
    return words, writes


def _strip_prefix(words: list[str]) -> list[str]:
    from swarmbench.studies.auditor.labels import _PREFIX

    while words and (words[0] in _PREFIX or re.match(r"^\w+=", words[0]) or words[0] == "timeout"
                     or re.match(r"^-", words[0]) or re.match(r"^\d+[smh]?$", words[0])):
        words = words[1:]
    return words


# --- steps --------------------------------------------------------------------------------------------------


def shell_steps(shell: str) -> list[Step]:
    """The steps of a shell text (rule 2)."""
    from swarmbench.studies.auditor.labels import raw_segments

    steps: list[Step] = []
    for seg in raw_segments(shell or ""):
        words, writes = _redirect_targets(seg)
        words = _strip_prefix(words)
        if not words:
            if writes:
                steps.append(Step("edit", ",".join(sorted({_base(w) for w in writes}))))
            continue
        step = _program_step(words, writes)
        if step is not None:
            steps.append(step)
    return steps


def _program_step(words: list[str], writes: list[str]) -> Step | None:
    """One simple command's step. A redirect into a file makes it an ``edit`` when the program itself only
    prints or reads (``cat > f <<EOF``, ``echo x > f``); a program that runs (``python3 x.py > log``)
    stays a ``run``."""
    step = _base_step(words)
    printing = _prog(words) in ("echo", "printf", "cat")
    if writes and (step is None or step.category == "read" or printing):
        return Step("edit", ",".join(sorted({_base(w) for w in writes})))
    return step


def _base_step(words: list[str]) -> Step | None:
    from swarmbench.studies.auditor.labels import CONTENT_PROGS, INSPECT_PROGS, PROCESS_PROGS

    p = _prog(words)
    if p.startswith("#"):
        return None  # a comment
    args = [w for w in words[1:] if not w.startswith("-")]
    paths = [_base(w) for w in args if _is_path(w)]
    sub = _subcommand(words)
    if p in TRIVIAL:
        return None
    if p in SUBMIT_PROGS or (p == "taskdesk" and sub == "submit"):
        return Step("submit", " ".join([_program_label(words), *paths]).strip())
    if p in BOARD_PROGS:
        if sub in POST_SUBCOMMANDS or "-m" in words or "--message" in words:
            return Step("message", _post_recipient(words, sub) or _program_label(words))
        return Step("read", _program_label(words))
    if p in WAIT_PROGS or (p == "tail" and ("-f" in words or "-F" in words)):
        return Step("wait", "")
    if p == "git":
        if sub in GIT_EDIT:
            return Step("edit", f"git {sub}")
        if sub in GIT_READ or sub is None:
            return Step("read", f"git {sub}" if sub else "git")
        return Step("run", f"git {sub}")
    if p == "sed" and any(w.startswith("-i") for w in words):
        return Step("edit", ",".join(sorted(set(paths))) or "sed")
    if p in EDIT_PROGS:
        return Step("edit", ",".join(sorted(set(paths))) or p)
    if p in CONTENT_PROGS or p in INSPECT_PROGS or p in PROCESS_PROGS or p in READ_EXTRA:
        return Step("read", ",".join(sorted(set(paths))) or p)
    return Step("run", " ".join([_program_label(words), *paths]).strip())


_VALUE_OPTIONS = {"-m", "--message", "-f", "--file", "-t", "--title", "--to", "-c", "--channel"}


def _post_recipient(words: list[str], sub: str | None) -> str:
    """The channel or recipient of a posting command: the first plain argument after the subcommand
    (``board post <channel> -m ...``), or the value of ``--to``/``--channel``."""
    for opt in ("--to", "--channel", "-c"):
        if opt in words and words.index(opt) + 1 < len(words):
            return words[words.index(opt) + 1]
    if sub not in POST_SUBCOMMANDS:
        return ""
    rest = words[words.index(sub) + 1:]
    k = 0
    while k < len(rest):
        w = rest[k]
        if w in _VALUE_OPTIONS:
            k += 2
            continue
        if w.startswith("-"):
            k += 1
            continue
        return w
    return ""


def _tool_target(args: dict[str, Any]) -> str:
    names = []
    for k in PATH_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            names.append(_base(v))
    return ",".join(sorted(set(names)))


def tool_steps(function: str, args: Any) -> list[Step]:
    """The steps of one tool call (rule 2)."""
    args = args if isinstance(args, dict) else {}
    if function in SHELL_TOOLS:
        cmd = args.get(SHELL_TOOLS[function])
        return shell_steps(" ".join(cmd) if isinstance(cmd, list) else str(cmd or ""))
    if function == "exec" and isinstance(args.get("input"), str):
        return codex_exec_steps(args["input"])
    if function == "call_mcp_tool":
        name = str(args.get("ToolName") or args.get("tool_name") or args.get("name") or "")
        inner = args.get("Arguments") or args.get("arguments") or {}
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except ValueError:
                inner = {}
        return tool_steps(name, inner) if name else [Step("other", function)]
    if SUBMIT_TOOLS.match(function):
        return [Step("submit", _tool_target(args) or function)]
    if MESSAGE_TOOLS.match(function) or re.search(r"send.*message|post_message", function, re.IGNORECASE):
        to = next((str(args[k]) for k in RECIPIENT_KEYS if isinstance(args.get(k), str | list) and args.get(k)), "")
        return [Step("message", to or function)]
    if WAIT_TOOLS.match(function):
        return [Step("wait", "")]
    if EDIT_TOOLS.match(function):
        target = _tool_target(args)
        if not target and isinstance(args.get("input"), str):
            target = ",".join(sorted({_base(m) for m in re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$",
                                                                    args["input"], re.MULTILINE)}))
        return [Step("edit", target or function)]
    if READ_TOOLS.match(function) or re.search(r"list_users", function):
        return [Step("read", _tool_target(args) or function)]
    return [Step("other", function)]


_JS_TOOL = re.compile(r"(?<![\w.$])tools\.(\w+)\s*\(")
_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^") | {""}


def js_code_mask(code: str) -> str:
    """The JavaScript text with the insides of strings, template literals, comments and regular-expression
    literals blanked out (same length), so only real code is searched for tool calls."""
    out = list(code)
    i, n = 0, len(code)
    last = ""  # the last significant code character, to tell a regex literal from a division

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            end = code.find("\n", i)
            end = n if end < 0 else end
            blank(i, end)
            i = end
            continue
        if ch == "/" and nxt == "*":
            end = code.find("*/", i + 2)
            end = n if end < 0 else end + 2
            blank(i, end)
            i = end
            continue
        if ch in "\"'`" or (ch == "/" and last in _REGEX_BEFORE):
            quote, k, in_class = ch, i + 1, False
            while k < n:
                c = code[k]
                if c == "\\":
                    k += 2
                    continue
                if quote == "/":
                    if c == "[":
                        in_class = True
                    elif c == "]":
                        in_class = False
                    elif c == "/" and not in_class or c == "\n":
                        break
                elif c == quote:
                    break
                k += 1
            blank(i + 1, k)
            i = k + 1
            last = "a"  # a literal is a value
            continue
        if not ch.isspace():
            last = ch
        i += 1
    return "".join(out)


def _js_object_arg(text: str, start: int) -> str:
    """The text of a JavaScript call's argument list, from just after ``(`` to the matching ``)``."""
    depth, i, quote = 1, start, None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return text[start:]


def _js_string_field(arg: str, key: str) -> str | None:
    """A string field of a JavaScript object literal: ``key: "..."``, ``"key": "..."``, ``key: '...'`` or a
    template literal without substitutions."""
    m = re.search(r'(?:^|[{,\s])"?' + re.escape(key) + r'"?\s*:\s*', arg)
    if not m:
        return None
    rest = arg[m.end():]
    if rest.startswith('"'):
        m2 = re.match(r'"((?:[^"\\]|\\.)*)"', rest, re.DOTALL)
        if m2:
            try:
                return json.loads('"' + m2.group(1) + '"')
            except ValueError:
                return m2.group(1)
    if rest.startswith("'"):
        m2 = re.match(r"'((?:[^'\\]|\\.)*)'", rest, re.DOTALL)
        if m2:
            return m2.group(1).replace("\\'", "'").replace("\\n", "\n")
    if rest.startswith("`"):
        m2 = re.match(r"`((?:[^`\\]|\\.)*)`", rest, re.DOTALL)
        if m2:
            return m2.group(1)
    return None


def _js_first_string(arg: str) -> str | None:
    m = re.match(r'\s*"((?:[^"\\]|\\.)*)"', arg, re.DOTALL)
    if m:
        try:
            return json.loads('"' + m.group(1) + '"')
        except ValueError:
            return m.group(1)
    m = re.match(r"\s*`((?:[^`\\]|\\.)*)`", arg, re.DOTALL)
    return m.group(1) if m else None


def codex_exec_steps(code: str) -> list[Step]:
    """The steps of a Codex ``exec`` call's JavaScript (rule 2)."""
    steps: list[Step] = []
    for m in _JS_TOOL.finditer(js_code_mask(code)):  # calls in code only, not in strings or comments
        name = m.group(1)
        arg = _js_object_arg(code, m.end())
        if name == "exec_command":
            cmd = _js_string_field(arg, "cmd")
            steps.extend(shell_steps(cmd) if cmd is not None else [Step("run", "exec_command")])
        elif name == "apply_patch":
            patch = _js_string_field(arg, "input") or _js_first_string(arg) or ""
            files = re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", patch, re.MULTILINE)
            steps.append(Step("edit", ",".join(sorted({_base(f) for f in files})) or "apply_patch"))
        elif name == "write_stdin":
            chars = _js_string_field(arg, "chars")
            steps.append(Step("wait", "") if not chars else Step("run", "write_stdin"))
        else:
            steps.extend(tool_steps(name, {}))
    return steps


# --- the action ---------------------------------------------------------------------------------------------


def call_text(function: str, args: Any) -> str:
    """A call's command, for the re-run rule: the shell text (or a Codex exec's code), or the tool with its
    arguments, whitespace runs made one space, the agent's own labels left out."""
    args = args if isinstance(args, dict) else {}
    if function in SHELL_TOOLS:
        cmd = args.get(SHELL_TOOLS[function])
        return _norm_space(" ".join(cmd) if isinstance(cmd, list) else str(cmd or ""))
    if function == "exec" and isinstance(args.get("input"), str):
        return _norm_space(args["input"])
    clean = {k: v for k, v in args.items() if k not in LABEL_KEYS and v is not None and v is not False}
    return _norm_space(function + " " + json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str))


def _tool_calls(output: dict[str, Any] | None) -> list[dict[str, Any]]:
    choices = (output or {}).get("choices") or []
    if not choices:
        return []
    msg = choices[0].get("message") or {}
    return list(msg.get("tool_calls") or [])


def read_action(output: dict[str, Any] | None, target_function: str, target_arguments: Any) -> Action:
    """The next action in a model answer (raw ``ModelOutput`` JSON), by rules 1-6."""
    calls = _tool_calls(output)
    if not calls:
        return Action("stop", "", [], 0, "")
    call = calls[0]
    function = str(call.get("function") or "")
    args = call.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"input": args}
    text = call_text(function, args)
    if isinstance(target_arguments, str):
        try:
            target_arguments = json.loads(target_arguments)
        except ValueError:
            target_arguments = {}
    steps = tool_steps(function, args)
    short = text if len(text) <= 300 else text[:297] + "..."
    if text and text == call_text(target_function, target_arguments):
        return Action("rerun", "", steps, len(calls), short)
    ranked = [c for c in RANK if any(s.category == c for s in steps)]
    if not ranked:
        return Action("other", function, steps, len(calls), short)
    category = ranked[0]
    first = next(s for s in steps if s.category == category)
    target = "" if category == "wait" else first.target
    return Action(category, target, steps, len(calls), short)


def same(a: Action | dict[str, Any], b: Action | dict[str, Any], strict: bool = True) -> bool:
    """Rule 7: the same category, and (strict) the same target."""
    ca = a.category if isinstance(a, Action) else a["category"]
    cb = b.category if isinstance(b, Action) else b["category"]
    if ca != cb:
        return False
    if not strict:
        return True
    ta = a.target if isinstance(a, Action) else a["target"]
    tb = b.target if isinstance(b, Action) else b["target"]
    return (ta or "") == (tb or "")
