"""Stage 1 of the auditor prediction study: the commands table.

One row per command an agent ran in a real run, with the output the agent got back and how long
it took (docs/research/auditor-prediction-plan.md). Every later stage builds on this table.

Where things come from:

- **Commands and results** come from the judge's event ledger (``swarmbench.judge.ledger``). It
  reads every model call once, skips context a model call only re-sent, restores the tool-call ids
  Antigravity renames between turns, and links each call to its result. Only calls the model
  really made count as commands (a call that only appears in re-sent or rewritten context is a
  copy of an earlier one), so compaction and restarts never count a command twice.
- **Antigravity background tasks.** A command still running after a few seconds becomes a
  background task: its immediate result only says "Tool is running as a background task with task
  id X", and the real output arrives later in a ``<SYSTEM_MESSAGE>`` ("Task id "X" finished with
  result: ...") inside a later tool result. The two are joined by task id; the message's own
  timestamp says when the task finished.
- **Timing**, per harness, best source first:

  - ``harness_stream`` (Claude Code): Claude Code's own transcript (its ``stream-json`` output,
    which Inspect records while polling the harness process) stamps each tool use and each tool
    result; the duration is the difference (same clock, millisecond precision).
  - ``harness_walltime`` (Codex): Codex reports ``Wall time N seconds`` in every tool result.
  - ``notice_seen`` (Claude Code background commands, ``run_in_background``): when the agent's
    model first saw the harness's notice that the command ended (an upper bound).
  - ``async_done`` (Antigravity background tasks): the finish time in the task's message, minus
    the time the call was made. The message gives whole seconds (cut, not rounded), so half a
    second is added; checked against the process start times swarmbench's process accounting
    logs, this matches the run time of the same command when it finished in the foreground.
  - ``next_request``: the time from the call to the agent's next model request carrying its
    result. The harness sends that request as soon as the results are in, so this includes a
    little harness overhead and, for several calls in one turn, the wait for the slowest.

  Inspect's own "sandbox" events are not a timing source: in these harnesses the agent's commands
  run inside the harness process, and the sandbox events are plumbing (polling the harness
  process, swarmbench's monitors and watchers), never the agent's commands.

Real runs only: a run counts when at least one agent uses a real model (not Inspect's
``mockllm``) and that model answered at least once.

Usage::

    uv run python -m swarmbench.studies.auditor.extract inventory
    uv run python -m swarmbench.studies.auditor.extract sample
    uv run python -m swarmbench.studies.auditor.extract all
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_RUNS = Path(__file__).resolve().parents[4] / "runs"
"""Default runs folder: ``<checkout>/runs`` (a worktree points at the main checkout's runs)."""


def default_runs_dir() -> Path:
    """The main checkout's runs folder, also from inside a worktree (.claude/worktrees/<name>)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "worktrees" and parent.parent.name == ".claude":
            return parent.parent.parent / "runs"
    return REPO_RUNS


HARNESSES = {
    "claude_code": "claude_code",
    "codex_cli": "codex",
    "codex": "codex",
    "antigravity": "antigravity",
    "react": "react",
}

COLUMNS = [
    "key",
    "run_id",
    "scenario",
    "harness",
    "agent_model",
    "agent",
    "seq",
    "function",
    "command",
    "arguments",
    "output",
    "output_status",
    "exit_code",
    "t_call",
    "t_result",
    "t_seen",
    "duration_s",
    "timing_source",
    "time_basis",
    "background",
    "task_id",
    "turn_calls",
    "log_file",
    "call_event",
    "result_event",
]
"""The commands table's columns (see the brief; ``arguments``, ``t_seen``, ``task_id`` and
``turn_calls`` are additions):

- ``arguments``: the call's full arguments as JSON (``command`` holds just the shell text when
  the tool is a shell).
- ``t_call``: when the agent got the model answer that made the call.
- ``t_seen``: when the agent sent its next model request carrying the result (the result had
  reached it by then).
- ``time_basis``: ``gateway`` when ``t_call`` and ``t_seen`` come from swarmbench's gateway log
  (exact; see ``gateway_times``), ``inspect`` when from Inspect's model-call times (about a second
  late), ``mixed`` when one of each.
- ``task_id``: the id that ties a command to its later result: an Antigravity background task
  (``<conversation>/task-N``), a Claude Code background command (its short id), or a Codex
  process session (``session:N``; the later ``wait``/``exec`` calls that read the same process
  carry the same id).
- ``background``: the command went on running after the agent got its first answer. For
  Antigravity and Claude Code, ``output`` is the final result (Antigravity) or the end notice
  (Claude Code; the output itself went to a file). For Codex, ``output`` is what the call
  returned so far; the rest is in later rows with the same ``task_id``.
- ``turn_calls``: how many tool calls the same model response made (the ``next_request`` duration
  of each is the time until all were done).
"""

SHELL_ARG = {
    "Bash": "command",
    "bash": "command",
    "run_command": "CommandLine",
    "exec": "input",
    "shell": "command",
    "exec_command": "cmd",
    "local_shell": "command",
}
"""The argument holding the command text, for tools that run one."""


def is_mock_model(model: str | None) -> bool:
    m = (model or "").lower()
    return not m or m.startswith("mockllm") or m in {"model", "mockllm/model"}


# --------------------------------------------------------------------------------------------
# Output parsing (pure functions; unit tested)

_SYSMSG_INTRO = re.compile(r"\n{0,2}The following is a <SYSTEM_MESSAGE> not actually sent by the user\.")
_SYSMSG = re.compile(r"<SYSTEM_MESSAGE>(.*?)</SYSTEM_MESSAGE>", re.DOTALL)
_BG_START = re.compile(r"Tool is running as a background task with task id: (\S+)")
_TASK_DONE = re.compile(
    r"\[Message\] timestamp=(?P<ts>\S+) sender=(?P<sender>\S+).*?content=Task id \"(?P<task>[^\"]+)\" "
    r"(?P<verb>finished|failed)(?: with result)?:?(?P<body>.*)",
    re.DOTALL,
)
_TASK_LOG = re.compile(r"\n*Log: file://\S*\s*\Z")


def unwrap_envelope(text: str) -> str:
    """Antigravity's tool results arrive as JSON ``{"output": "..."}``: return the inner text."""
    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            d = json.loads(s)
        except ValueError:
            return text
        if isinstance(d, dict) and set(d) == {"output"} and isinstance(d["output"], str):
            return d["output"]
    return text


def split_system_messages(text: str) -> tuple[str, list[str]]:
    """A tool result's own text, and the ``<SYSTEM_MESSAGE>`` blocks the harness appended to it
    (notices about other tasks, not this command's output)."""
    blocks = _SYSMSG.findall(text)
    if not blocks:
        return text, []
    m = _SYSMSG_INTRO.search(text)
    cut = m.start() if m else text.find("<SYSTEM_MESSAGE>")
    return text[:cut], blocks


@dataclass
class TaskDone:
    task_id: str
    finished_at: datetime | None
    verb: str
    output: str


def parse_task_done(block: str) -> TaskDone | None:
    """A background task's finish notice (the inside of one ``<SYSTEM_MESSAGE>``)."""
    m = _TASK_DONE.search(block)
    if not m:
        return None
    body = _TASK_LOG.sub("", m.group("body")).strip("\n")
    try:
        when = datetime.fromisoformat(m.group("ts"))
    except ValueError:
        when = None
    return TaskDone(m.group("task"), when, m.group("verb"), body)


def background_task_id(text: str) -> str | None:
    m = _BG_START.search(text)
    return m.group(1) if m else None


_REMINDER = re.compile(r"\s*<system-reminder>.*?</system-reminder>\s*", re.DOTALL)
_CC_BG_START = re.compile(r"\ACommand running in background with ID: (\w+)")
_CC_NOTICE = re.compile(r"<task-notification>(.*?)</task-notification>", re.DOTALL)


def strip_reminders(text: str) -> str:
    """A Claude Code tool result without the ``<system-reminder>`` blocks the harness appends
    (token counts, notices about other tasks): those are not the command's output."""
    if "<system-reminder>" not in text:
        return text
    return _REMINDER.sub("\n", text).rstrip("\n") + ("\n" if text.endswith("\n") else "")


@dataclass
class Notice:
    task_id: str
    tool_use_id: str | None
    status: str | None
    text: str


def parse_cc_notices(text: str) -> list[Notice]:
    """Claude Code's background-task notices (``<task-notification>``) in a text."""
    out = []
    for body in _CC_NOTICE.findall(text):

        def tag(name: str, body: str = body) -> str | None:
            m = re.search(rf"<{name}>(.*?)</{name}>", body, re.DOTALL)
            return m.group(1).strip() if m else None

        if tag("task-id"):
            out.append(Notice(tag("task-id") or "", tag("tool-use-id"), tag("status"), body.strip()))
    return out


def cc_background_id(text: str) -> str | None:
    m = _CC_BG_START.search(text.lstrip())
    return m.group(1) if m else None


_SESSION = re.compile(r'"session_id":\s*(\d+)')


def codex_session(text: str) -> tuple[str | None, bool]:
    """A Codex result's process session id, and whether the process was still running (it
    returned a session id and no exit code: the rest of its output comes from later calls)."""
    m = _SESSION.search(text)
    if not m:
        return None, False
    return f"session:{m.group(1)}", '"exit_code"' not in text


_WALL = re.compile(r"^(?:Script (?:completed|failed)[^\n]*\n)?Wall time:? ([0-9.]+) seconds", re.MULTILINE)


def codex_wall_time(text: str) -> float | None:
    m = _WALL.search(text[:400])
    return float(m.group(1)) if m else None


_AG_EXIT = re.compile(r"The command failed with exit code: (-?\d+)")
_CC_EXIT = re.compile(r"\A(?:Error: )?Exit code (-?\d+)")
_CC_NOT_RUN = re.compile(
    r"Error|Command (?:did not complete|timed out)|\[Request interrupted|<tool_use_error>|"
    r"Command running in background"
)
_CODEX_EXIT = re.compile(
    r'"exit_code":\s*(-?\d+)|^(?:Exit code|Process exited with code):? (-?\d+)', re.MULTILINE
)


def exit_code(harness: str, function: str, text: str | None, is_error: bool | None = None) -> int | None:
    """The exit code a shell command's output reports, when it says (else None)."""
    if text is None:
        return None
    if harness == "antigravity":
        if function != "run_command":
            return None
        m = _AG_EXIT.search(text)
        if m:
            return int(m.group(1))
        return 0 if "The command completed successfully" in text else None
    if harness == "claude_code":
        if function not in ("Bash", "bash"):
            return None
        m = _CC_EXIT.search(text.lstrip())
        if m:
            return int(m.group(1))
        if is_error is not None:
            return 0 if is_error is False else None
        # Claude Code starts a failed command's result with "Exit code N"; any other start that
        # is not an error or interruption notice means the command exited 0
        return None if _CC_NOT_RUN.match(text.lstrip()) else 0
    if harness == "codex":
        codes = [int(a or b) for a, b in _CODEX_EXIT.findall(text)]
        return codes[0] if len(set(codes)) == 1 else None
    return None


_TRUNCATED = re.compile(
    r"<truncated \d+ lines>"  # Antigravity
    r"|\[\.\.\. ?\d+ (?:lines|characters) truncated ?\.\.\.\]|\.\.\. \[\d+ lines truncated\] \.\.\."  # Claude Code
    r"|…\d+ tokens truncated…|Total output lines: \d+"  # Codex
    r"|Output too large|output truncated|\(truncated\)",
    re.IGNORECASE,
)


def is_truncated(text: str | None) -> bool:
    return bool(text) and bool(_TRUNCATED.search(text))


# --------------------------------------------------------------------------------------------
# Claude Code's own transcript (stream-json), recorded in the harness-process polls


@dataclass
class StreamTimes:
    use: dict[str, datetime] = field(default_factory=dict)
    result: dict[str, datetime] = field(default_factory=dict)
    is_error: dict[str, bool] = field(default_factory=dict)


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_stream_lines(lines: Iterable[str], out: StreamTimes | None = None) -> StreamTimes:
    """Tool-use and tool-result times from Claude Code ``stream-json`` lines."""
    out = out or StreamTimes()
    for line in lines:
        line = line.strip()
        if not line.startswith("{") or '"tool_' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        when = _ts(d.get("timestamp"))
        msg = d.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if when is None or not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if d.get("type") == "assistant" and c.get("type") == "tool_use" and c.get("id"):
                out.use.setdefault(c["id"], when)
            elif d.get("type") == "user" and c.get("type") == "tool_result" and c.get("tool_use_id"):
                out.result.setdefault(c["tool_use_id"], when)
                out.is_error.setdefault(c["tool_use_id"], bool(c.get("is_error")))
    return out


def harness_streams(events: list[Any]) -> dict[int, str]:
    """Each polled harness process's output (stdout then stderr per poll), by process id."""
    chunks: dict[int, list[str]] = defaultdict(list)
    for e in events:
        if (
            getattr(e, "event", None) != "sandbox"
            or not e.input
            or "exec_remote_poll" not in str(e.input)[:80]
        ):
            continue
        try:
            pid = json.loads(e.input)["params"]["pid"]
            res = json.loads(e.output or "{}").get("result") or {}
        except (ValueError, KeyError, TypeError):
            continue
        if res.get("stdout"):
            chunks[pid].append(res["stdout"])
    return {pid: "".join(c) for pid, c in chunks.items()}


def claude_code_stream_times(events: list[Any]) -> StreamTimes:
    out = StreamTimes()
    for text in harness_streams(events).values():
        if '"tool_use' in text:
            parse_stream_lines(text.splitlines(), out)
    return out


# --------------------------------------------------------------------------------------------
# Gateway times: when each model request really left the agent, and when its answer finished


def gateway_times(
    sample: Any, agents: dict[str, dict[str, Any]]
) -> dict[str, tuple[datetime, datetime | None]]:
    """Model-call event uuid -> (request sent, response finished), from swarmbench's gateway.

    Every model request goes through the gateway, which logs when the request arrived and when
    the connection carrying the answer closed. The engine already pairs each Inspect model call
    with its gateway request (``swarm_request_actors``: request id -> gateway sequence number).
    Inspect's own model-call times are about a second late (the bridge's relay), so these are the
    times the agent really sent a request and got its answer. Runs before the gateway kept its
    log (early October) have none."""
    from swarmbench.judge.extract import _request_id_of

    store = sample.store or {}
    records = store.get("swarm_bridge_requests") or []
    actors = store.get("swarm_request_actors") or {}
    if not records or not isinstance(actors, dict):
        return {}
    requests: dict[tuple[Any, int], dict[str, Any]] = {}
    closes: dict[tuple[Any, str], float] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("t") == "request" and r.get("seq") is not None:
            requests[(r.get("sandbox"), int(r["seq"]))] = r
        elif r.get("t") == "close" and r.get("conn") and r.get("end") is not None:
            closes[(r.get("sandbox"), str(r["conn"]))] = float(r["end"])
    out: dict[str, tuple[datetime, datetime | None]] = {}
    for e in sample.events or []:
        if getattr(e, "event", None) != "model" or not e.uuid:
            continue
        rid = _request_id_of(e)
        info = actors.get(rid) if rid else None
        if not isinstance(info, dict) or len(info.get("gateway_seq") or []) != 1:
            continue
        sandbox = (agents.get(str(info.get("bridge_of"))) or {}).get("sandbox")
        req = requests.get((sandbox, int(info["gateway_seq"][0])))
        if req is None or req.get("start") is None:
            continue
        end = closes.get((sandbox, str(req.get("conn"))))
        out[e.uuid] = (
            datetime.fromtimestamp(float(req["start"]), UTC),
            datetime.fromtimestamp(end, UTC) if end is not None else None,
        )
    return out


# --------------------------------------------------------------------------------------------
# Reading runs


def find_logs(runs_dir: Path) -> list[tuple[str, Path]]:
    """(run id, Inspect log) for every run folder with exactly one log; runs are sorted by id."""
    out = []
    for d in sorted(runs_dir.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        logs = sorted((d / "logs").glob("*.eval"))
        if logs:
            out.append((d.name, logs[-1]))
    return out


def read_sample(log_path: Path) -> Any:
    from inspect_ai.log import read_eval_log

    log = read_eval_log(str(log_path), resolve_attachments=True)
    if not log.samples:
        raise ValueError(f"{log_path} has no samples")
    return log.samples[0]


def _agents_meta(sample: Any) -> list[dict[str, Any]]:
    return list(((sample.metadata or {}).get("swarm") or {}).get("agents") or [])


def _scenario(sample: Any, run_dir: Path) -> str:
    meta = (sample.metadata or {}).get("swarm") or {}
    if meta.get("scenario"):
        return str(meta["scenario"])
    try:
        return str(json.loads((run_dir / "status.json").read_text())["scenario"])
    except (OSError, ValueError, KeyError):
        return run_dir.name.split("_", 1)[-1]


def inventory_row(run_id: str, run_dir: Path, log_path: Path, sample: Any) -> dict[str, Any]:
    agents = _agents_meta(sample)
    models = sorted({str(a.get("model")) for a in agents if a.get("model")})
    harnesses = sorted({HARNESSES.get(str(a.get("harness")), str(a.get("harness"))) for a in agents})
    real_calls = 0
    tool_calls = 0
    for e in sample.events or []:
        if getattr(e, "event", None) != "model" or is_mock_model(getattr(e, "model", None)):
            continue
        if e.output and e.output.choices and not getattr(e, "error", None):
            real_calls += 1
            tool_calls += len(e.output.message.tool_calls or [])
    state = None
    try:
        state = json.loads((run_dir / "status.json").read_text()).get("state")
    except (OSError, ValueError):
        pass
    real = real_calls > 0 and any(not is_mock_model(m) for m in models)
    return {
        "run_id": run_id,
        "scenario": _scenario(sample, run_dir),
        "real": real,
        "harnesses": ",".join(harnesses),
        "agent_models": ",".join(models),
        "n_agents": len(agents),
        "teams": len(((sample.metadata or {}).get("swarm") or {}).get("teams") or []),
        "n_model_calls": real_calls,
        "n_tool_calls": tool_calls,
        "state": state,
        "log_file": log_path.name,
        "started": sample.events[0].timestamp if sample.events else None,
    }


# --------------------------------------------------------------------------------------------
# The commands of one run


def _model_events(sample: Any) -> dict[str, Any]:
    return {e.uuid: e for e in sample.events or [] if getattr(e, "event", None) == "model" and e.uuid}


def _command_text(function: str, args: dict[str, Any]) -> str:
    key = SHELL_ARG.get(function)
    if key and isinstance(args.get(key), str):
        return args[key]
    return json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)


def _secs(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def build_ledger_unredacted(sample: Any) -> Any:
    """The judge's ledger for one sample, without the model-name masking it applies when a run
    mixes models (the study needs outputs exactly as the agents saw them)."""
    from swarmbench.judge.extract import extract_sample
    from swarmbench.judge.ledger import build_ledger

    inputs = extract_sample(sample)
    inputs = dataclasses.replace(
        inputs, agents_meta=[{k: v for k, v in a.items() if k != "model"} for a in inputs.agents_meta]
    )
    return build_ledger(sample, inputs)


def extract_run(
    run_id: str, run_dir: Path, log_path: Path, sample: Any | None = None
) -> list[dict[str, Any]]:
    """The commands table rows for one run."""
    sample = sample if sample is not None else read_sample(log_path)
    agents = {a["name"]: a for a in _agents_meta(sample) if a.get("name")}
    scenario = _scenario(sample, run_dir)
    ledger = build_ledger_unredacted(sample)
    models = _model_events(sample)
    gw = gateway_times(sample, agents)
    stream = (
        claude_code_stream_times(sample.events or [])
        if any(HARNESSES.get(str(a.get("harness"))) == "claude_code" for a in agents.values())
        else StreamTimes()
    )

    by_id = {e.id: e for e in ledger.events}
    linked: dict[str, str] = {}
    for link in ledger.links:
        if link.kind == "call_result":
            linked.setdefault(link.src, link.dst)
    # every result an agent's model was shown, by (agent, tool-call id), in time order
    results: dict[tuple[str, str], list[Any]] = defaultdict(list)
    # every background-task notice, earliest first: task id -> (notice, ledger event carrying it)
    done: dict[str, tuple[TaskDone, Any]] = {}  # Antigravity
    cc_done: dict[str, tuple[Notice, Any]] = {}  # Claude Code
    for e in ledger.events:
        if e.kind == "tool_result" and e.actor in agents and e.meta.get("tool_call_id"):
            results[(e.actor, e.meta["tool_call_id"])].append(e)
        if e.kind not in ("tool_result", "prompt", "system"):
            continue
        text = ledger.text(e)
        if "SYSTEM_MESSAGE" in text:
            for block in _SYSMSG.findall(unwrap_envelope(text)):
                notice = parse_task_done(block)
                if notice and notice.task_id not in done:
                    done[notice.task_id] = (notice, e)
        if "<task-notification>" in text:
            for n in parse_cc_notices(text):
                cc_done.setdefault(n.task_id, (n, e))

    calls = [
        e
        for e in ledger.events
        if e.kind == "tool_call" and not e.meta.get("from_input") and e.actor in agents
    ]
    # the same call id made again later by the same agent (Antigravity's short ids can repeat)
    next_same: dict[str, datetime | None] = {}
    last: dict[tuple[str, str], Any] = {}
    for c in reversed(calls):
        k = (c.actor, c.meta.get("tool_call_id"))
        next_same[c.id] = last[k].time if k in last else None
        last[k] = c
    turn_size = Counter(e.source.split("#", 1)[0] for e in calls)

    rows: list[dict[str, Any]] = []
    seq: Counter[str] = Counter()
    keys: Counter[str] = Counter()
    for c in calls:
        agent = c.actor
        meta = agents[agent]
        harness = HARNESSES.get(str(meta.get("harness")), str(meta.get("harness")))
        call_id = c.meta.get("tool_call_id") or c.id
        function = c.meta.get("function") or ""
        src_uuid = c.source.split("#", 1)[0]
        args: dict[str, Any] = {}
        mev = models.get(src_uuid)
        if mev is not None and mev.output and mev.output.choices:
            for tc in mev.output.message.tool_calls or []:
                if tc.id == call_id:
                    args = dict(tc.arguments or {})
                    break
        if not args:
            from swarmbench.judge.ledger import call_arguments

            args = call_arguments(ledger.text(c))

        t_call = c.time
        basis = []
        if src_uuid in gw and gw[src_uuid][1] is not None:
            t_call = gw[src_uuid][1]
            basis.append("gateway")
        else:
            basis.append("inspect")

        def seen_time(ev: Any, basis: list[str] = basis) -> datetime | None:
            uuid = ev.source.split("#", 1)[0]
            if uuid in gw:
                basis.append("gateway")
                return gw[uuid][0]
            basis.append("inspect")
            return ev.time

        # the result: the ledger's own link, else the first result under this id after the call
        res = by_id.get(linked.get(c.id, ""))
        if res is not None and res.time and c.time and res.time < c.time - timedelta(seconds=1):
            res = None  # a result shown before the call was made belongs to an earlier call
        if res is None:
            until = next_same.get(c.id)
            res = next(
                (
                    r
                    for r in results.get((agent, call_id), [])
                    if r.time and c.time and r.time >= c.time and (until is None or r.time < until)
                ),
                None,
            )

        out: str | None = None
        status = "missing"
        t_seen = seen_time(res) if res is not None else None
        result_event = res.source.split("#", 1)[0] if res is not None else None
        background = False
        task_id = None
        t_result = None
        duration = None
        source = None
        is_error = stream.is_error.get(call_id)
        if res is not None:
            raw = ledger.text(res)
            cc_task = None
            if harness == "antigravity":
                raw, _ = split_system_messages(unwrap_envelope(raw))
                task_id = background_task_id(raw)
            elif harness == "claude_code":
                raw = strip_reminders(raw)
                cc_task = cc_background_id(raw)
            elif harness == "codex":
                task_id, background = codex_session(raw)
            out = raw
            status = "complete"
            if cc_task:
                # Claude Code background command: the notice says when it ended and how (its
                # output went to a file the agent reads with a separate command)
                background, task_id = True, cc_task
                cc_notice = cc_done.get(cc_task)
                if cc_notice is None:
                    out, status, t_seen, result_event = None, "missing", None, None
                else:
                    out = cc_notice[0].text
                    basis.pop()
                    t_seen = seen_time(cc_notice[1])
                    result_event = cc_notice[1].source.split("#", 1)[0]
                    t_result, duration, source = t_seen, _secs(t_call, t_seen), "notice_seen"
            elif task_id and harness == "antigravity":
                background = True
                notice = done.get(task_id)
                if notice is None:
                    out, status, t_seen, result_event = None, "missing", None, None
                else:
                    out = notice[0].output
                    basis.pop()
                    t_seen = seen_time(notice[1])
                    result_event = notice[1].source.split("#", 1)[0]
                    if notice[0].finished_at is not None:
                        # the notice's time is cut to whole seconds: take the middle of that second
                        t_result = notice[0].finished_at + timedelta(seconds=0.5)
                        duration = _secs(t_call, t_result)
                        source = "async_done"
        if status == "complete" and is_truncated(out):
            status = "truncated"

        if duration is None and status != "missing":
            if harness == "claude_code" and call_id in stream.use and call_id in stream.result:
                duration = _secs(stream.use[call_id], stream.result[call_id])
                source = "harness_stream"
            elif harness == "codex" and out is not None and (wall := codex_wall_time(out)) is not None:
                duration = wall
                source = "harness_walltime"
            elif t_seen is not None and t_call is not None:
                duration = _secs(t_call, t_seen)
                source = "next_request"
            if duration is not None and t_result is None and t_call is not None:
                t_result = t_call + timedelta(seconds=duration)
        if duration is not None and duration < 0:
            # a finish logged before the gateway saw the answer end (the harness can start a
            # command while the answer's last bytes are still streaming): too short to measure
            duration, t_result = 0.0, t_call

        base = f"{run_id}/{agent}/{call_id}"
        keys[base] += 1
        key = base if keys[base] == 1 else f"{base}~{keys[base]}"
        rows.append(
            {
                "key": key,
                "run_id": run_id,
                "scenario": scenario,
                "harness": harness,
                "agent_model": meta.get("model"),
                "agent": agent,
                "seq": seq[agent],
                "function": function,
                "command": _command_text(function, args),
                "arguments": json.dumps(args, sort_keys=True, ensure_ascii=False, default=str),
                "output": out,
                "output_status": status,
                "exit_code": exit_code(harness, function, out, is_error),
                "t_call": t_call,
                "t_result": t_result,
                "t_seen": t_seen,
                "duration_s": duration,
                "timing_source": source,
                "time_basis": basis[0] if len(set(basis)) == 1 else "mixed",
                "background": background,
                "task_id": task_id,
                "turn_calls": turn_size[src_uuid],
                "log_file": log_path.name,
                "call_event": src_uuid,
                "result_event": result_event,
            }
        )
        seq[agent] += 1
    return rows


# --------------------------------------------------------------------------------------------
# Tables


def to_frame(rows: list[dict[str, Any]]) -> Any:
    import pandas as pd

    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in ("t_call", "t_result", "t_seen"):
        df[col] = pd.to_datetime(df[col], utc=True)
    df["exit_code"] = df["exit_code"].astype("Int64")
    df["seq"] = df["seq"].astype("int64")
    df["turn_calls"] = df["turn_calls"].astype("int64")
    df["background"] = df["background"].astype(bool)
    df["duration_s"] = df["duration_s"].astype("float64")
    return df


def _inventory_job(args: tuple[str, str, str]) -> dict[str, Any]:
    run_id, run_dir, log_path = args
    try:
        sample = read_sample(Path(log_path))
        return inventory_row(run_id, Path(run_dir), Path(log_path), sample)
    except Exception as exc:  # a broken log is reported, not fatal
        return {
            "run_id": run_id,
            "real": False,
            "error": f"{type(exc).__name__}: {exc}",
            "log_file": Path(log_path).name,
        }


def _extract_job(args: tuple[str, str, str, str]) -> tuple[str, int, str | None]:
    run_id, run_dir, log_path, cache = args
    try:
        rows = extract_run(run_id, Path(run_dir), Path(log_path))
        to_frame(rows).to_parquet(cache, index=False)
        return run_id, len(rows), None
    except Exception as exc:
        import traceback

        return run_id, 0, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"


def build_inventory(runs_dir: Path, out_dir: Path, workers: int = 1) -> Any:
    import pandas as pd

    jobs = [(rid, str(runs_dir / rid), str(p)) for rid, p in find_logs(runs_dir)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(_inventory_job, jobs))
    df = pd.DataFrame(rows).sort_values("run_id").reset_index(drop=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "runs_inventory.parquet", index=False)
    df.drop(columns=[c for c in ("started",) if c in df]).to_csv(out_dir / "runs_inventory.csv", index=False)
    return df


def build_commands(
    runs_dir: Path, out_dir: Path, run_ids: list[str], name: str, workers: int = 1, reuse: bool = True
) -> Any:
    """Extract the given runs (cached per run under ``extract_cache/``) into ``<name>.parquet``."""
    import pandas as pd

    cache_dir = out_dir / "extract_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    logs = dict(find_logs(runs_dir))
    jobs = []
    for rid in run_ids:
        cache = cache_dir / f"{rid}.parquet"
        if reuse and cache.exists() and cache.stat().st_mtime >= Path(__file__).stat().st_mtime:
            continue
        jobs.append((rid, str(runs_dir / rid), str(logs[rid]), str(cache)))
    errors = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for rid, n, err in pool.map(_extract_job, jobs):
            print(f"  {rid}: {n} commands" + (f"  ERROR {err}" if err else ""), file=sys.stderr)
            if err:
                errors.append(rid)
    if errors:
        raise SystemExit(f"extraction failed for {errors}")
    df = pd.concat([pd.read_parquet(cache_dir / f"{rid}.parquet") for rid in run_ids], ignore_index=True)
    if df["key"].duplicated().any():
        raise SystemExit(f"duplicate keys: {df.loc[df['key'].duplicated(), 'key'].head().tolist()}")
    df.to_parquet(out_dir / f"{name}.parquet", index=False)
    return df


SAMPLE_RUNS = [
    "2026-10-23T071032_proof-conference-planted-small",  # Antigravity, 5 agents
    "2026-10-20T150600_rl-coding-env-v2",  # Claude Code (Claude Sonnet 5.5)
    "2026-10-20T155724_rl-coding-env-v2",  # Codex (GPT-5.6 Sol)
]


def coverage(df: Any) -> str:
    """A plain-text coverage summary of a commands table."""
    import pandas as pd

    lines = []
    g = df.groupby(["scenario", "harness"])
    tab = pd.DataFrame(
        {
            "runs": g["run_id"].nunique(),
            "commands": g.size(),
            "missing_output": g["output_status"].apply(lambda s: (s == "missing").mean()).round(3),
            "truncated": g["output_status"].apply(lambda s: (s == "truncated").mean()).round(3),
            "timed": g["duration_s"].apply(lambda s: s.notna().mean()).round(3),
            "background": g["background"].mean().round(3),
        }
    )
    lines.append(tab.to_string())
    lines.append("")
    lines.append("timing source by harness (share of commands):")
    lines.append(
        pd.crosstab(df["harness"], df["timing_source"].fillna("none"), normalize="index").round(3).to_string()
    )
    lines.append("")
    lines.append("functions by harness:")
    for h, s in df.groupby("harness")["function"]:
        lines.append(f"  {h}: " + ", ".join(f"{k} {v}" for k, v in s.value_counts().head(12).items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=["inventory", "sample", "all"])
    ap.add_argument("--runs-dir", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument(
        "--workers", type=int, default=1, help="parallel processes (each holds one run log in memory)"
    )
    ap.add_argument("--runs", nargs="*", help="run ids (default: the sample runs, or every real run)")
    ap.add_argument("--fresh", action="store_true", help="ignore the per-run cache")
    a = ap.parse_args(argv)
    runs_dir = a.runs_dir or default_runs_dir()
    out_dir = a.out_dir or runs_dir / "_studies" / "auditor"
    if a.what == "inventory":
        df = build_inventory(runs_dir, out_dir, a.workers)
        print(df.drop(columns=[c for c in ("started", "log_file") if c in df]).to_string())
        return 0
    if a.what == "sample":
        df = build_commands(
            runs_dir, out_dir, a.runs or SAMPLE_RUNS, "commands_sample", a.workers, not a.fresh
        )
    else:
        inv_path = out_dir / "runs_inventory.parquet"
        import pandas as pd

        inv = (
            pd.read_parquet(inv_path) if inv_path.exists() else build_inventory(runs_dir, out_dir, a.workers)
        )
        run_ids = a.runs or inv.loc[inv["real"].fillna(False).astype(bool), "run_id"].tolist()
        df = build_commands(runs_dir, out_dir, run_ids, "commands", a.workers, not a.fresh)
    print(coverage(df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
