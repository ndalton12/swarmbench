"""Per-agent roles, scenario images (advanced.sandbox_image) and the larger agent cap."""

from __future__ import annotations

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
        layers[tag] = [build_args["BASE_IMAGE"], "scenario-layer"]

    monkeypatch.setattr(image, "_docker_build", build)
    monkeypatch.setattr(image, "_layers", lambda tag: layers.get(tag, [tag]))
    monkeypatch.setattr(image, "image_exists", lambda tag: tag in images)
    monkeypatch.setattr(image, "DOCKER_DIR", tmp_path / "docker")
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
