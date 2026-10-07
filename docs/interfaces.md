# Interfaces between components

This document is the contract between the six parts of swarmbench. Read `docs/plan.md` first for the design.

| Part | Owns | Code |
|---|---|---|
| Engine | Inspect task, orchestrator, container image and compose file, agents and harnesses, message bus and board, budgets, encounters, live status | `swarmbench/engine/`, `docker/` |
| Runner | CLI, detached runs, experiments, process management, prices and cost estimates | `swarmbench/cli.py`, `swarmbench/runner/`, `swarmbench/costs.py`, `prices.yaml` |
| Observer | live monitor (approval rules, container watcher, memory watchdog), judge (Scout scanners, summarizer) | `swarmbench/monitor/`, `swarmbench/judge/` |
| Scenarios | the two first scenarios | `scenarios/` |
| Realism | realism checklist and reviews | `docs/realism.md`, review notes |
| Designer | `swarm design new/iterate` | `swarmbench/design/` |

The shared types already exist, and every part codes against them:

- `swarmbench/config.py`: the scenario schema;
- `swarmbench/types.py`: agents, messages, bridge connections, monitor flags, reports, cost and status;
- `swarmbench/paths.py`: the run folder;
- `swarmbench/status.py`: the live status writer.

To change any of these, message the lead first rather than changing them on your own branch.

## 1. Inside a team container (engine builds, everyone relies on)

One container per team, with Inspect sandbox names `team-<name>` (a single-swarm scenario has one sandbox, `team-swarm`, which is also the default sandbox).

| Path | Owner and mode | What it is |
|---|---|---|
| `/workspace` | root:`staff`, 2775 | Shared work area, seeded from the scenario's `workspace/`. Every agent user is in group `staff`. |
| `/board/<channel>/` | root:`staff`, 3775 (sticky and setgid) | Board posts, one file per post: `<unix-ms>-<user>.md`. The author is the file's owner. |
| `/opt/<...>` | root, read-only mount | The scenario's `protected/` folder, e.g. a checker. |
| `/home/<user>` | `<user>`, 755 | An agent's home. Its Claude Code and Codex config folders live here. |
| `/usr/local/bin/board` | root, 755 | The board command (see section 4). |
| `/usr/local/lib/swarmbench/watcher` | root, 700 | The container watcher, started by the observer as root. |
| `/var/lib/swarmbench/` | root, 700 | The watcher's output (section 3), read by the host. |

- Users are `u01`, `u02`, ... with uids 2001, 2002, ..., from `advanced.username_pattern`.
- The hostname comes from `advanced.hostname`; the default is a plausible, neutral server name.
- Capabilities: everything is dropped except `SETUID`/`SETGID`. Only root holds those, and agents run as non-root with `no-new-privileges`.
- Every container carries the label `swarmbench.run=<run_id>`.

## 2. The Inspect log (engine writes, judge and runner read)

**Task and sample.**

- The task is `swarm`, built by `swarmbench.engine.swarm_task(scenario, run_dir, dry_run=False)`.
- Each epoch is one sample.
- Sample metadata `swarm` is a dict with these keys:
  - `scenario`, the scenario name;
  - `run_id`;
  - `teams`, a list of `{name, sandbox, agents}`;
  - `agents`, a list of `AgentInfo` dicts.

**Per-agent spans.** Every agent runs inside `span(name=<agent name>, type="agent")`, and all its events belong there, including inspect-swe model events. The judge finds each agent's timeline by span name. When agent A uses agent B's bridge, the resulting events land in B's span. That can't be prevented, so the attribution records below exist to correct for it.

**Events.** Each is written with `transcript().info(payload, source=...)`. Each payload is a pydantic model dumped with `mode="json"`.

| `source` | Payload | Written by |
|---|---|---|
| `swarm.message` | `SwarmMessage` | engine, for every direct message and every board post as soon as it is seen |
| `swarm.read` | `{"agent", "ids": [...]}` | engine, when an agent is shown messages (it checks messages, reads the board through `board read`, or gets a notice) |
| `swarm.bridge` | `BridgeConnection` | observer, only for cross-agent connections (normal own-bridge use is just counted) |
| `swarm.monitor` | `MonitorFlag` | observer |
| `swarm.foreign_turn` | `{"bridge_of", "reason"}` | engine, when a model call in B's timeline doesn't continue B's conversation |
| `swarm.encounter` | `{"via", "path"}` | engine, when the encounter channel opens |
| `swarm.agent_stopped` | `{"agent", "reason"}` | engine, when an agent finishes, crashes, runs out of budget or is stopped |

**Sample store at the end** (engine writes, except where marked):

| Key | Contents |
|---|---|
| `swarm_messages` | list of `SwarmMessage` |
| `swarm_agent_usage` | `{agent: {"tokens", "input_tokens", "output_tokens", "usd", "stop_reason"}}`, counted by bridge, so it includes use by other agents |
| `swarm_bridge_summary` | `{owner_agent: {peer_agent_or_uid: connection_count}}` (observer) |
| `swarm_protected_hashes` | `{"before": {path: sha256}, "after": {...}}` |
| `swarm_problems` | list of plain-text reasons: crashes, content-filter blocks, monitor or user stop, watcher evidence lost, watchdog stop |

## 3. Monitor (observer writes, engine calls)

```python
# swarmbench/monitor/__init__.py
def approval_policies(scenario: Scenario, run_dir: RunDir) -> list[ApprovalPolicy]: ...
@asynccontextmanager
async def watch(scenario: Scenario, run_dir: RunDir, agents: list[AgentInfo],
                sandboxes: dict[str, SandboxEnvironment]) -> AsyncIterator[None]: ...
def stop_requested() -> str | None: ...
```

- **`approval_policies`** is passed to the Inspect task as `approval=`. It sees `react` tool calls and inspect-swe tool calls proposed through the bridge. It finds the calling agent with `swarmbench.engine.current_agent()`, which the engine provides from a context variable set inside each agent's task. Approval only sees what a model proposed, so flags from it say "proposed".
- **`watch`** wraps the whole swarm. Inside, the observer:
  - starts the root watcher in each team container with `exec(..., user="root")`;
  - polls the watcher's output under `/var/lib/swarmbench/` every second;
  - turns the output into `MonitorFlag`s and `BridgeConnection`s;
  - writes them to the transcript and to `run_dir.monitor`;
  - runs the host memory watchdog.

  On exit it collects final hashes. If the watcher dies or its output is tampered with, the observer adds a `swarm_problems` entry.
- **`stop_requested`** returns a reason once a critical flag (or the watchdog) wants the run stopped. The engine checks it about once a second, stops every agent, records the reason in `swarm_problems`, and finishes normally so the log is complete.
- The watcher writes JSON lines to `/var/lib/swarmbench/`:
  - `procs.jsonl`: `{t, pid, ppid, uid, cmd}` for each new process;
  - `conns.jsonl`: `{t, port, peer_uid}` for each connection to a bridge port;
  - `files.jsonl`: `{t, path, uid, event}` for protected and board paths, and new setuid files.

  The engine tells the observer which ports are bridge ports through `AgentInfo.bridge_port`.

## 4. Messaging (engine)

- **Direct.** The tools are `send_message(to, text)`, `check_messages()` and `list_agents()`. Each agent gets its own tool instances, with its identity bound when the tools are created. inspect-swe agents get the same tools through `bridged_tools`, bound to their own bridge, so a message sent through B's bridge records `sender=B` and `via_bridge_of=B`. If the watcher saw A connected at that moment, the engine also adds a `MonitorFlag` saying A acted as B. With `notice` delivery, new messages are added as one short digest to the agent's next model call: through the generate filter for inspect-swe agents, and through an `on_continue`/message hook for `react`.
- **Board.** `board post <channel> [file|-]`, `board read [<channel>] [--new] [--limit N]` and `board channels`.
  - The board command records what each user has read in `~/.board_seen`.
  - The engine scans `/board` every 2 s, as root through `exec`, and turns new files into `SwarmMessage(channel="board")`, with `sender` taken from the file's owner.
  - A post's text signed with someone else's name sets `claimed_sender`.
  - Reads come from the `~/.board_seen` files, or from watcher records of processes reading `/board`, and are logged as `swarm.read`.

## 5. Engine ↔ runner

```python
# swarmbench/engine/__init__.py
def swarm_task(scenario: Scenario, run_dir: RunDir, dry_run: bool = False) -> Task: ...
def run_scenario(scenario: Scenario, run_dir: RunDir, status: StatusWriter,
                 dry_run: bool = False) -> list[Path]: ...   # returns .eval paths
def current_agent() -> str | None: ...
```

- `run_scenario` writes `scenario.yaml` and `provenance.json`, calls `inspect_ai.eval(...)` with `log_dir=run_dir.logs`, `model_cost_config=costs.model_cost_config()`, and `cost_limit=scenario.max_cost`, and then returns the log paths.
- While it runs, it calls `status.update(...)` with `state`, `agents_total`, `agents_active`, `messages`, `monitor_flags`, `swarm_cost` and `compose_project`.
- Dry runs use `mockllm/model` for every role. The mock agents produce a few tool calls, a board post and a direct message, so every path is exercised.
- The runner owns:
  - `swarmbench/costs.py`: `model_cost_config()`, `price_of(model)`, `estimate_max_cost(scenario)` and `usage_cost(model_usage)`;
  - `prices.yaml` at the repo root;
  - everything to do with processes: detaching, `ps`, `stop` (graceful first, then `docker compose down` for the run's label), and `cleanup`.

## 6. Judge (observer)

```python
# swarmbench/judge/__init__.py
def judge_run(run_dir: RunDir, model: str | None = None) -> list[JudgeReport]: ...
```

- **Inputs.** It reads `run_dir.eval_logs()`, runs Scout scanners into `run_dir.scans`, and writes `report.md` and `report.json` (one `JudgeReport` per sample). It also updates `status.json` (`verdict`, `headline`, `judge_cost`).
- **Per-agent scanners** run on each agent's span timeline (`TranscriptContent(timeline=True)`).
- **Team scanners** run on the `swarm.message` events.
- **Attribution.** `swarm.bridge`, `swarm.foreign_turn` and the bridge summary are used to attribute events that landed in the wrong agent's span. Anything unresolved is reported as unknown.
- **Cost.** The judge uses the same `prices.yaml` through `swarmbench.costs`.
- **Quotes.** Every quote is checked word for word against the log, and `coverage` is always filled in.
- **Dry runs.** With `mockllm`, the judge must still produce a well-formed report.

## 7. Scenarios and designer

- A scenario folder holds `scenario.yaml`, `prompt.md`, `workspace/`, an optional `protected/`, and `notes.md`. `notes.md` is never copied into a container.
- `swarm check <dir>` validates the folder against `config.py` and runs a dry run. It must pass before a scenario is marked ready.
- Files agents can see must follow `docs/realism.md`.
- The designer interface:

  ```python
  def new_scenario(idea: str, out_dir: Path | None = None, model: str | None = None) -> Path: ...
  def iterate_scenario(scenario_dir: Path, run_dirs: list[RunDir], out_dir: Path | None = None,
                       model: str | None = None) -> Path: ...
  ```

  `new_scenario` writes `scenarios/<slug>/`. `iterate_scenario` writes `<scenario>_v2/` (or the next free number) with `CHANGES.md`, and never overwrites anything.
