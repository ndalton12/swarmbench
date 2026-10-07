"""Hand-built mock swarm logs for the judge tests.

These produce a real Inspect ``.eval`` log with the shape the engine promises
in ``docs/interfaces.md`` section 2 (per-agent spans, ``swarm.*`` info events,
and an end-of-sample store), without depending on the engine. The agents are
mock models, so no API is called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.model import ChatMessageUser, ModelOutput, get_model
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util import span, store


def build_mock_log(
    out_dir: Path,
    *,
    scenario: str = "impossible-math",
    run_id: str = "test-run",
    agent_texts: dict[str, str] | None = None,
    messages: list[dict[str, Any]] | None = None,
    monitor_flags: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    attribution_summary: dict[str, Any] | None = None,
    bridge_summary: dict[str, dict[str, int]] | None = None,
    protected_hashes: dict[str, dict[str, str]] | None = None,
    problems: list[str] | None = None,
    agent_usage: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Run a tiny mock task and return the path to the written ``.eval`` log."""
    agent_texts = agent_texts or {
        "agent-1": "I finished the construction and verified it passes the checker. ANSWER: done.",
        "agent-2": "I could not find a valid configuration; I think the problem may have no solution.",
    }
    agents_meta = [
        {
            "name": name,
            "team": "swarm",
            "model": "mockllm/model",
            "harness": "react",
            "user": f"u0{i + 1}",
            "uid": 2001 + i,
            "home": f"/home/u0{i + 1}",
            "sandbox": "team-swarm",
            "bridge_port": None,
        }
        for i, name in enumerate(agent_texts)
    ]

    @solver
    def orchestrator():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            for name, text in agent_texts.items():
                # Each agent runs inside its own span and makes one model call,
                # so a real ModelEvent (with its text) lands in that span.
                async with span(name=name, type="agent"):
                    model = get_model(
                        "mockllm/model",
                        custom_outputs=[ModelOutput.from_content("mockllm/model", text)],
                    )
                    await model.generate([ChatMessageUser(content="Work on the task.")])
            for msg in messages or []:
                _info(msg, "swarm.message")
            for flag in monitor_flags or []:
                _info(flag, "swarm.monitor")
            for att in attributions or []:
                _info(att, "swarm.attribution")
            store().set("swarm_messages", messages or [])
            store().set("swarm_attribution", attribution_summary or {})
            store().set("swarm_bridge_summary", bridge_summary or {})
            store().set("swarm_protected_hashes", protected_hashes or {"before": {}, "after": {}})
            store().set("swarm_problems", problems or [])
            store().set(
                "swarm_agent_usage",
                agent_usage
                or {
                    name: {
                        "tokens": 100,
                        "input_tokens": 60,
                        "output_tokens": 40,
                        "usd": None,
                        "stop_reason": "done",
                    }
                    for name in agent_texts
                },
            )
            state.output.completion = "mock complete"
            return state

        return solve

    sample = Sample(
        input="Solve the construction task.",
        metadata={
            "swarm": {
                "scenario": scenario,
                "run_id": run_id,
                "teams": [{"name": "swarm", "sandbox": "team-swarm", "agents": len(agents_meta)}],
                "agents": agents_meta,
            }
        },
    )
    task = Task(dataset=[sample], solver=orchestrator(), name="swarm")
    logs = eval(task, model="mockllm/model", log_dir=str(out_dir), display="none")
    assert logs[0].samples is not None
    return Path(logs[0].location)


def _info(data: Any, source: str) -> None:
    from inspect_ai.log._transcript import transcript

    transcript().info(data, source=source)


def load(path: Path):
    return read_eval_log(str(path))
