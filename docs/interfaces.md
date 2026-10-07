# Interfaces between components

This is the contract between the engine, runner, observer (monitor and judge), scenarios and designer. Shared types live in `src/swarmbench/config.py` (scenario schema), `src/swarmbench/types.py` (messages, flags, reports, status, cost) and `src/swarmbench/paths.py` (run folder). If you need a change to any of these, message the lead first. Don't change them on your own branch.

## What the Inspect log contains (engine writes, judge reads)

- **Task.** `swarmbench/swarm`, created by `swarmbench.engine.swarm_task(scenario, run_dir)`. Each epoch has one sample.
- **Sample metadata `swarm`:** a dict with these keys:
  - `scenario`: the scenario name.
  - `teams`: a list of `{name, agents}`.
  - `agents`: a list with one entry per agent, `{name, team, model, harness, user, uid, home, bridge_ports, sandbox}`, where `sandbox` is the name of the team's container.
  - `notes_path`: path to the scenario's notes file.
- **Per-agent span.** Every agent runs inside `span(name=<agent name>, type="agent")`. Anything that agent does, including inspect-swe model events, must sit inside its span. The judge finds per-agent timelines by span name.
- **Messages.** Each message, from either the bus or the board, is logged as `transcript().info(SwarmMessage.model_dump(mode="json"), source="swarm.message")`. When an agent is later shown a message, `swarm.read` is logged with `{"agent": ..., "ids": [...]}`.
- **Monitor flags.** Each flag is logged as an `info` event with `source="swarm.monitor"` holding a `MonitorFlag` payload, and is also appended to `monitor.jsonl`.
- **Encounter.** When the channel opens, the engine logs `info` with `source="swarm.encounter"` and the payload `{"time", "via", "path"}`.
- **Sample store, written at the end:**
  - `swarm_messages`: a list of `SwarmMessage` dicts.
  - `swarm_agent_usage`: `{agent: {"tokens", "input_tokens", "output_tokens", "usd", "stopped_reason"}}`.
  - `swarm_protected_hashes`: `{"before": {...}, "after": {...}}`.
- **Problems.** Any agent crash, content-filter block, or run stopped by the monitor or a user is recorded in the store as `swarm_problems`, a list of plain-text reasons. The judge reports these in the report's `coverage` field.

## Monitor (observer writes, engine calls)

- `swarmbench.monitor.approval_policies(scenario, run_dir) -> list[ApprovalPolicy]`: passed to the Inspect task as `approval=`. It applies to `react` tools and to tool calls returned through the inspect-swe bridge. To learn which agent made a call, it uses the active span or a context variable set by the engine. The engine exposes `swarmbench.engine.current_agent() -> str | None` for this.
- `swarmbench.monitor.watch(scenario, run_dir, agents: list[AgentInfo], sandboxes: dict[str, SandboxEnvironment]) -> AsyncContextManager`: the engine wraps the swarm in this. `sandboxes` holds one container per team, and `AgentInfo` gives each agent's uid and bridge ports. Inside, the observer runs the container watcher as a background task. It uses uids to attribute processes, and bridge-port connections from the wrong uid to flag impersonation.
- `swarmbench.monitor.stop_requested() -> str | None`: the engine checks this between steps. When it returns a reason, the engine stops every agent, records the reason in `swarm_problems`, and finishes cleanly. The monitor can also raise through Inspect's own mechanism if that is simpler. Agree the approach with the engine teammate.

## Judge (observer)

- `swarmbench.judge.judge_run(run_dir, model=None) -> list[JudgeReport]`: reads `run_dir.eval_logs()`, runs Scout scanners into `run_dir.scans`, then writes `report.md` and `report.json`. Every quote must be checked against the transcript.

## Engine ↔ runner

- `swarmbench.engine.run_scenario(scenario, run_dir, dry_run=False, status=StatusWriter) -> list[Path]`: runs the eval and returns the log paths. With `dry_run`, every model role uses `mockllm/model`.
- `swarmbench.status.StatusWriter`: the runner creates it. The engine calls `update(**fields)` whenever things change; the writer throttles disk writes to every few seconds.
- The engine labels every container `swarmbench.run=<run_id>` and records `compose_project` in the status, so `stop --hard` and `cleanup` can find it.
- The engine reads `prices.yaml` through `swarmbench.costs.model_cost_config()`, which the runner owns.

## Scenario files (scenarios and designer write, engine reads)

- The folder layout and YAML fields are defined in `config.py`. `swarm check <dir>` must pass, and it runs a mock dry run.
- Agent-visible files must follow `docs/realism.md`. `notes.md` is never mounted into any container.
