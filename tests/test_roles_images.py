"""Per-agent roles, scenario images (advanced.sandbox_image) and the larger agent cap."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from swarmbench.config import MAX_AGENTS_PER_RUN, load_scenario
from swarmbench.engine import image
from swarmbench.engine.harness import react_system
from swarmbench.engine.layout import agent_infos
from swarmbench.engine.orchestrator import Swarm
from swarmbench.runner.check import validate_scenario

ROLES = (
    "  roles:\n"
    "    - {name: algebra, prompt: roles/algebra.md}\n"
    "    - {name: analysis, prompt: roles/analysis.md}\n"
)


def scenario_dir(tmp_path: Path, yaml: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "scenario.yaml").write_text(yaml)
    (tmp_path / "prompt.md").write_text("Hello {user}.\n")
    (tmp_path / "notes.md").write_text("notes\n")
    (tmp_path / "workspace").mkdir(exist_ok=True)
    (tmp_path / "workspace" / "README").write_text("hi\n")
    (tmp_path / "roles").mkdir(exist_ok=True)
    (tmp_path / "roles" / "algebra.md").write_text("Persona: Algebra. You are {user}.\n")
    (tmp_path / "roles" / "analysis.md").write_text("Persona: Analysis.\n")
    return tmp_path


# ------------------------------------------------------------------ roles


def test_roles_are_given_out_in_turn(tmp_path):
    s = load_scenario(scenario_dir(tmp_path, "name: x\nswarm:\n  agents: 5\n" + ROLES))
    assert [a.role for a in agent_infos(s)] == ["algebra", "analysis", "algebra", "analysis", "algebra"]


def test_team_roles_override_and_no_roles(tmp_path):
    yaml = (
        "name: x\nswarm:\n  agents: 2\n"
        + ROLES
        + "teams:\n  - {name: red}\n  - {name: blue, roles: []}\n"
        + "encounter: {after: 30m, via: board_channel, path: commons}\n"
    )
    s = load_scenario(scenario_dir(tmp_path, yaml))
    roles = {a.name: a.role for a in agent_infos(s)}
    assert roles == {
        "red-agent-1": "algebra",
        "red-agent-2": "analysis",
        "blue-agent-1": None,
        "blue-agent-2": None,
    }


def test_role_text_reaches_each_agents_system_prompt(tmp_path):
    s = load_scenario(scenario_dir(tmp_path, "name: x\nswarm:\n  agents: 3\n" + ROLES))
    swarm = Swarm(s, None, "run-roles", None)
    texts = {name: art.role_text for name, art in swarm.agents.items()}
    assert texts["agent-1"] == "Persona: Algebra. You are u01."
    assert texts["agent-2"] == "Persona: Analysis."
    assert texts["agent-3"] == "Persona: Algebra. You are u03."
    art = swarm.agents["agent-1"]
    system = react_system(art.info, "host1", art.role_text)
    assert system.startswith("Your account on the shared Linux server host1 is u01.")
    assert system.endswith("\n\nPersona: Algebra. You are u01.")
    assert react_system(art.info, "host1") == react_system(art.info, "host1", "")


def test_missing_role_file_is_a_problem(tmp_path):
    folder = scenario_dir(tmp_path, "name: x\nswarm:\n  agents: 2\n" + ROLES)
    (folder / "roles" / "analysis.md").unlink()
    problems = validate_scenario(load_scenario(folder)).problems
    assert any("role analysis" in p and "roles/analysis.md" in p for p in problems)


def test_duplicate_role_names_and_paths_outside(tmp_path):
    with pytest.raises(Exception, match="role names must be unique"):
        load_scenario(
            scenario_dir(
                tmp_path, "name: x\nswarm:\n  roles: [{name: a, prompt: r1.md}, {name: a, prompt: r2.md}]\n"
            )
        )
    for path in ("/etc/passwd", "../secret.md"):
        with pytest.raises(Exception, match="inside the scenario folder"):
            load_scenario(
                scenario_dir(tmp_path / "b", f"name: x\nswarm:\n  roles: [{{name: a, prompt: '{path}'}}]\n")
            )


def test_role_text_naming_another_home_does_not_change_attribution():
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser

    from swarmbench.engine.bridgefilter import IDENTITY_LINE, BridgeFilter
    from swarmbench.engine.harness import with_role

    role = "Persona: review the drafts in /home/u02/results."
    identity = IDENTITY_LINE.format(host="h", user="u01", home="/home/u01")
    messages = [ChatMessageSystem(content=with_role(identity, role)), ChatMessageUser(content="task")]
    plain = BridgeFilter(
        agent="agent-1", user="u01", peers={"u01": "agent-1", "u02": "agent-2"}, budget=10_000, meter=None
    )
    assert plain.classify(messages).verdict == "foreign_unknown"
    aware = BridgeFilter(
        agent="agent-1",
        user="u01",
        peers={"u01": "agent-1", "u02": "agent-2"},
        budget=10_000,
        meter=None,
        role_texts=(role,),
    )
    assert aware.classify(messages).verdict == "own"


def test_role_names_are_identifiers(tmp_path):
    with pytest.raises(Exception, match="role names"):
        load_scenario(
            scenario_dir(tmp_path, "name: x\nswarm:\n  roles: [{name: 'Number Theory', prompt: r.md}]\n")
        )


# ------------------------------------------------------------------ agent cap


def test_agent_cap_allows_a_hundred(tmp_path):
    s = load_scenario(scenario_dir(tmp_path, "name: x\nswarm: {agents: 100}\n"))
    users = [a.user for a in agent_infos(s)]
    assert len(users) == 100 and users[-1] == "u100" and len(set(users)) == 100
    with pytest.raises(Exception):
        load_scenario(scenario_dir(tmp_path / "b", f"name: x\nswarm: {{agents: {MAX_AGENTS_PER_RUN + 1}}}\n"))


# ------------------------------------------------------------------ scenario images

DOCKERFILE = "ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nRUN echo hi\n"


def with_image(tmp_path: Path, spec: str, dockerfile: str | None = DOCKERFILE) -> Path:
    folder = scenario_dir(tmp_path, f"name: x\nadvanced:\n  sandbox_image: {spec}\n")
    if dockerfile is not None:
        (folder / "image").mkdir()
        (folder / "image" / "Dockerfile").write_text(dockerfile)
        (folder / "image" / "setup.sh").write_text("true\n")
    return folder


def test_dockerfile_or_tag(tmp_path):
    s = load_scenario(with_image(tmp_path, "image/Dockerfile"))
    assert image.sandbox_dockerfile(s) == tmp_path / "image" / "Dockerfile"
    assert image.sandbox_image_problems(s) == []
    for spec in ("registry.example/lean:4.21", "registry.example/dockerfile-tools:latest", "lean"):
        tag = load_scenario(with_image(tmp_path / "t", spec, dockerfile=None))
        assert image.sandbox_dockerfile(tag) is None and image.sandbox_image_problems(tag) == []


def test_dockerfile_problems(tmp_path):
    missing = load_scenario(with_image(tmp_path / "a", "image/lean.Dockerfile"))
    assert "missing" in image.sandbox_image_problems(missing)[0]
    outside = load_scenario(with_image(tmp_path / "b", "../Dockerfile"))
    assert "outside the scenario folder" in image.sandbox_image_problems(outside)[0]
    not_on_base = load_scenario(with_image(tmp_path / "c", "image/Dockerfile", "FROM debian:12\n"))
    # a download stage from another image is fine as long as the final stage is on the base
    staged = (
        "ARG BASE_IMAGE\nFROM debian:12 AS build\nRUN true\nFROM ${BASE_IMAGE}\nCOPY --from=build /x /x\n"
    )
    assert (
        image.sandbox_image_problems(load_scenario(with_image(tmp_path / "e", "image/Dockerfile", staged)))
        == []
    )
    last_not_base = "ARG BASE_IMAGE\nFROM ${BASE_IMAGE} AS tools\nFROM debian:12\n"
    assert image.sandbox_image_problems(
        load_scenario(with_image(tmp_path / "f", "image/Dockerfile", last_not_base))
    )
    assert "must build on the base image" in image.sandbox_image_problems(not_on_base)[0]
    linked = with_image(tmp_path / "d", "image/Dockerfile")
    (linked / "image" / "link").symlink_to("/etc/passwd")
    assert "symlink" in image.sandbox_image_problems(load_scenario(linked))[0]
    # validate_scenario (swarm check) reports them too
    assert any("must build on the base image" in p for p in validate_scenario(not_on_base).problems)


@pytest.fixture
def fake_docker(monkeypatch, tmp_path):
    built: list[tuple] = []
    images: set[str] = set()

    layers: dict[str, list[str]] = {}

    def build(context, tag, dockerfile=None, build_args=None):
        built.append((context, tag, dockerfile, build_args))
        images.add(tag)
        layers[tag] = [(build_args or {}).get("BASE_IMAGE", "debian"), "scenario-layer"]

    monkeypatch.setattr(image, "_docker_build", build)
    monkeypatch.setattr(image, "_layers", lambda tag: layers.get(tag, [tag]))
    monkeypatch.setattr(image, "image_exists", lambda tag: tag in images)
    monkeypatch.setattr(image, "DOCKER_DIR", tmp_path / "docker")
    monkeypatch.setattr(image, "SCENARIO_BUILD_LOCK", tmp_path / "scenario-build.lock")
    return built, images


def test_scenario_image_is_built_once_on_the_base(tmp_path, fake_docker):
    built, _ = fake_docker
    s = load_scenario(with_image(tmp_path / "s", "image/Dockerfile"))
    tag = image.build_scenario_image(s, "swarmbench-base:abc")
    assert tag.startswith("swarmbench-scenario:")
    ((context, built_tag, dockerfile, args),) = built
    assert context == tmp_path / "s" / "image" and dockerfile == context / "Dockerfile"
    assert built_tag == tag and args == {"BASE_IMAGE": "swarmbench-base:abc"}
    assert image.build_scenario_image(s, "swarmbench-base:abc") == tag and len(built) == 1
    # a new base or a changed file means a new image
    assert image.build_scenario_image(s, "swarmbench-base:def") != tag
    (tmp_path / "s" / "image" / "setup.sh").write_text("false\n")
    changed = image.build_scenario_image(s, "swarmbench-base:abc")
    assert changed != tag and len(built) == 3
    # so does an executable bit or a new empty folder
    (tmp_path / "s" / "image" / "setup.sh").chmod(0o755)
    executable = image.build_scenario_image(s, "swarmbench-base:abc")
    (tmp_path / "s" / "image" / "empty").mkdir()
    assert len({changed, executable, image.build_scenario_image(s, "swarmbench-base:abc")}) == 3


LEAN_MAIN = (
    "ARG BASE_IMAGE\nARG LEAN_IMAGE\nFROM ${LEAN_IMAGE} AS lean\n"
    "FROM ${BASE_IMAGE}\nCOPY --from=lean /srv /srv\nCOPY lean-check /usr/local/bin/\n"
)


def with_prebuilt_stage(tmp_path: Path) -> Path:
    folder = with_image(tmp_path, "image/Dockerfile", LEAN_MAIN)
    (folder / "image" / "lean-check").write_text("#!/bin/sh\n")
    (folder / "image" / "lean").mkdir()
    (folder / "image" / "lean" / "Dockerfile").write_text("FROM debian:12\nRUN slow-download\n")
    return folder


def test_prebuilt_stage_is_built_first_and_passed_as_a_build_arg(tmp_path, fake_docker):
    built, images = fake_docker
    s = load_scenario(with_prebuilt_stage(tmp_path / "s"))
    image_dir = tmp_path / "s" / "image"
    assert image.prebuilt_stages(image_dir) == [image_dir / "lean"]
    assert image.sandbox_image_problems(s) == []
    tag = image.build_scenario_image(s, "swarmbench-base:abc")
    (stage_ctx, stage_tag, stage_file, stage_args), (ctx, main_tag, _, args) = built
    assert stage_ctx == image_dir / "lean" and stage_file == stage_ctx / "Dockerfile"
    assert re.fullmatch(r"swarmbench-scenario-lean:[0-9a-f]{12}", stage_tag) and stage_args == {}
    assert ctx == image_dir and main_tag == tag
    assert args == {"BASE_IMAGE": "swarmbench-base:abc", "LEAN_IMAGE": stage_tag}

    # editing a file of the main image (or a new base) rebuilds only the main image
    (image_dir / "lean-check").write_text("#!/bin/sh\necho changed\n")
    assert image.build_scenario_image(s, "swarmbench-base:abc") != tag
    assert image.build_scenario_image(s, "swarmbench-base:new") != tag
    assert len(built) == 4
    assert all(b[0] == image_dir and b[3]["LEAN_IMAGE"] == stage_tag for b in built[2:])

    # the main image gone (e.g. pruned) but the stage still tagged: the stage is reused
    images.discard(built[-1][1])
    image.build_scenario_image(s, "swarmbench-base:new")
    assert [b[0] for b in built[4:]] == [image_dir]

    # a change inside the stage's folder rebuilds both, with a new stage tag
    (image_dir / "lean" / "Dockerfile").write_text("FROM debian:12\nRUN slower-download\n")
    newer = image.build_scenario_image(s, "swarmbench-base:new")
    (stage_ctx, new_stage_tag, *_), (_, newer_main, _, newer_args) = built[5:]
    assert stage_ctx == image_dir / "lean" and new_stage_tag != stage_tag
    assert newer == newer_main and newer_args["LEAN_IMAGE"] == new_stage_tag
    # so does an executable bit
    (image_dir / "lean" / "Dockerfile").chmod(0o755)
    image.build_scenario_image(s, "swarmbench-base:new")
    assert built[7][0] == image_dir / "lean" and built[7][1] not in (stage_tag, new_stage_tag)
    assert len(built) == 9


def test_prebuilt_stage_that_uses_the_base_depends_on_it(tmp_path, fake_docker):
    built, _ = fake_docker
    folder = with_prebuilt_stage(tmp_path / "s")
    s = load_scenario(folder)
    # used in FROM, or only declared (a RUN step can read it from the environment)
    for text in ("ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n", "FROM debian:12\narg base_image\nRUN env\n"):
        (folder / "image" / "lean" / "Dockerfile").write_text(text)
        start = len(built)
        image.build_scenario_image(s, "swarmbench-base:abc")
        image.build_scenario_image(s, "swarmbench-base:def")
        stages = [b for b in built[start:] if b[0].name == "lean"]
        assert [b[3] for b in stages] == [
            {"BASE_IMAGE": "swarmbench-base:abc"},
            {"BASE_IMAGE": "swarmbench-base:def"},
        ]
        assert stages[0][1] != stages[1][1]


def test_stage_args_and_prebuilt_stage_problems(tmp_path):
    assert image.stage_arg("lean") == "LEAN_IMAGE"
    assert image.stage_arg("mathlib-cache.v2") == "MATHLIB_CACHE_V2_IMAGE"
    folder = with_prebuilt_stage(tmp_path / "s")
    image_dir = folder / "image"
    (image_dir / "notes").mkdir()  # a subfolder without a Dockerfile is just part of the context
    (image_dir / "notes" / "x.txt").write_text("x\n")
    for name, text in (("Fetch", "FROM debian:12\n"), ("base", "FROM debian:12\n"), ("empty", "RUN true\n")):
        (image_dir / name).mkdir()
        (image_dir / name / "Dockerfile").write_text(text)
    (image_dir / "lean" / "link").symlink_to("/etc/passwd")
    problems = image.sandbox_image_problems(load_scenario(folder))
    assert [p.split(":")[0] for p in problems] == [
        "scenario folder contains a symlink",
        "prebuilt stage Fetch/",
        "prebuilt stage base/",
        "prebuilt stage empty/",
    ]
    assert "lowercase" in problems[1] and "clashes with BASE_IMAGE" in problems[2]
    assert "no FROM" in problems[3]


def test_scenario_image_whose_last_stage_is_not_on_the_base(tmp_path, fake_docker, monkeypatch):
    s = load_scenario(with_image(tmp_path / "s", "image/Dockerfile"))
    monkeypatch.setattr(
        image, "_layers", lambda tag: ["debian"] if tag.startswith("swarmbench-scenario") else [tag]
    )
    with pytest.raises(image.ImageError, match="final stage must be FROM"):
        image.build_scenario_image(s, "swarmbench-base:abc")


def test_no_sandbox_image_means_the_base(tmp_path, fake_docker):
    s = load_scenario(scenario_dir(tmp_path, "name: x\n"))
    assert image.build_scenario_image(s, "swarmbench-base:abc") == "swarmbench-base:abc"
    assert fake_docker[0] == []


def test_ready_made_image_must_contain_the_current_base(tmp_path, fake_docker, monkeypatch):
    layers = {"swarmbench-base:new": ["l1", "l2"], "lean:ok": ["l1", "l2", "l3"], "lean:old": ["l0", "l3"]}
    monkeypatch.setattr(image, "_layers", lambda tag: layers[tag])
    ok = load_scenario(with_image(tmp_path / "a", "lean:ok", dockerfile=None))
    assert image.build_scenario_image(ok, "swarmbench-base:new") == "lean:ok"
    old = load_scenario(with_image(tmp_path / "b", "lean:old", dockerfile=None))
    with pytest.raises(image.ImageError, match="not built on the current base image"):
        image.build_scenario_image(old, "swarmbench-base:new")


def test_team_image_builds_on_the_scenario_image(tmp_path, fake_docker, monkeypatch):
    from swarmbench.engine import task

    s = load_scenario(with_image(tmp_path / "s", "image/Dockerfile"))
    monkeypatch.setattr(task, "build_base_image", lambda: "swarmbench-base:abc")
    seen = []
    monkeypatch.setattr(
        task, "build_team_image", lambda scenario, i, base, **kw: seen.append(base) or "team:1"
    )
    assert task.build_images(s) == ["team:1"]
    assert seen[0].startswith("swarmbench-scenario:")


def test_connection_limit_grows_with_agents(tmp_path):
    from swarmbench.engine.task import eval_connections

    assert eval_connections(load_scenario(scenario_dir(tmp_path, "name: x\nswarm: {agents: 4}\n"))) is None
    assert (
        eval_connections(load_scenario(scenario_dir(tmp_path / "b", "name: x\nswarm: {agents: 100}\n")))
        == 102
    )


def test_cpu_limit_is_capped_at_dockers_cpus(tmp_path, monkeypatch):
    from swarmbench.engine import compose

    s = load_scenario(scenario_dir(tmp_path, "name: x\nswarm: {agents: 12}\nadvanced: {cpus: 16}\n"))
    monkeypatch.setattr(compose, "docker_cpus", lambda: 6)
    assert compose.team_limits(s, 0)["cpus"] == 6.0
    monkeypatch.setattr(compose, "docker_cpus", lambda: 64)
    assert compose.team_limits(s, 0)["cpus"] == 16
    monkeypatch.setattr(compose, "docker_cpus", lambda: None)
    assert compose.team_limits(s, 0)["cpus"] == 16


def test_shared_memory_is_added_once_per_container(tmp_path):
    from swarmbench.engine import compose

    s = load_scenario(
        scenario_dir(
            tmp_path,
            "name: x\nswarm: {agents: 3}\nadvanced: {memory_per_agent_mb: 500, memory_shared_mb: 2560}\n",
        )
    )
    assert compose.team_limits(s, 0)["mem_limit"] == f"{compose.MEMORY_BASE_MB + 2560 + 3 * 500}m"


# ------------------------------------------------------------------ restarts


def _swarm_with_sessions(tmp_path, monkeypatch, outcomes, extra=""):
    from inspect_ai.agent import AgentState

    from swarmbench.engine import orchestrator

    s = load_scenario(scenario_dir(tmp_path, f"name: x\nswarm: {{agents: 1}}\n{extra}"))
    swarm = Swarm(s, None, "run-restarts", None)
    seen: list[list] = []
    events: list[tuple] = []

    async def session(self, art, agent, messages, is_react, budget):
        seen.append(list(messages))
        return outcomes.pop(0), AgentState(messages=list(messages))

    async def no_wake(art):
        return None

    monkeypatch.setattr(orchestrator.Swarm, "_run_session", session)
    monkeypatch.setattr(orchestrator, "build_agent", lambda *a, **k: object())
    monkeypatch.setattr(orchestrator, "RESTART_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(swarm.wake, "wait_for_wake", no_wake)

    class Recorder:
        def info(self, data, source=None):
            events.append((source, data))

    monkeypatch.setattr(orchestrator, "transcript", lambda: Recorder())
    return swarm, seen, events


def test_a_crashed_agent_is_started_again_on_the_same_conversation(tmp_path, monkeypatch):
    import anyio

    from swarmbench.engine.orchestrator import RESTART_NOTE

    swarm, seen, events = _swarm_with_sessions(
        tmp_path, monkeypatch, ["crashed: RuntimeError: exited -9", "finished"]
    )
    art = swarm.agents["agent-1"]
    anyio.run(swarm._run_agent, art, None)
    assert art.stop_reason == "finished" and art.restarts == 1
    assert len(seen) == 2 and seen[1][: len(seen[0])] == seen[0] and seen[1][-1].text == RESTART_NOTE
    restarted = [d for source, d in events if source == "swarm.agent_restarted"]
    assert restarted == [
        {"agent": "agent-1", "attempt": 1, "of": 3, "after": "crashed: RuntimeError: exited -9"}
    ]
    assert swarm.agent_usage()["agent-1"]["restarts"] == 1


def test_restarts_are_bounded(tmp_path, monkeypatch):
    import anyio

    outcomes = ["crashed: boom"] * 3
    swarm, seen, _ = _swarm_with_sessions(
        tmp_path, monkeypatch, outcomes, "advanced: {extra: {max_restarts: 2}}\n"
    )
    art = swarm.agents["agent-1"]
    anyio.run(swarm._run_agent, art, None)
    assert len(seen) == 3 and art.restarts == 2 and art.stop_reason == "crashed: boom"


def test_only_a_crash_that_is_not_restarted_is_a_run_problem(tmp_path, monkeypatch):
    import anyio

    from swarmbench.engine import orchestrator

    problems: list[str] = []
    monkeypatch.setattr(orchestrator, "add_problem", problems.append)
    swarm, _, _ = _swarm_with_sessions(tmp_path, monkeypatch, ["crashed: boom", "finished"])
    anyio.run(swarm._run_agent, swarm.agents["agent-1"], None)
    assert problems == []
    swarm, _, _ = _swarm_with_sessions(
        tmp_path / "b", monkeypatch, ["crashed: boom"] * 2, "advanced: {extra: {max_restarts: 1}}\n"
    )
    anyio.run(swarm._run_agent, swarm.agents["agent-1"], None)
    assert problems == ["agent-1 crashed: boom"]
