"""Background programs (``services:``): config, checks, image, compose and monitor rules."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from swarmbench.config import Service, load_scenario
from swarmbench.engine.compose import team_service
from swarmbench.engine.image import service_problems, team_dockerfile
from swarmbench.engine.layout import SERVICE_UID_BASE, UID_BASE, service_users
from swarmbench.engine.services import start_script
from swarmbench.monitor import rules
from swarmbench.runner.check import validate_scenario
from tests.engine_helpers import make_scenario


def with_service(tmp_path, services, files=None):
    folder = make_scenario(tmp_path, services=services)
    for rel, text in (files or {}).items():
        path = folder / "services" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return folder


@pytest.mark.parametrize("name", ["Grader", "1grader", "a" * 25, "grader_x", ""])
def test_bad_service_names(name):
    with pytest.raises(ValidationError):
        Service(name=name, command="server.py")


@pytest.mark.parametrize("command", ["/usr/bin/python3", "../other/server.py", "bin/../../x"])
def test_command_stays_inside_the_folder(command):
    with pytest.raises(ValidationError):
        Service(name="grader", command=command)


def test_check_reports_missing_and_clashing_services(tmp_path):
    folder = with_service(
        tmp_path,
        [
            {"name": "grader", "command": "server.py"},
            {"name": "grader", "command": "server.py"},
            {"name": "u01", "command": "server.py"},
            {"name": "daemon", "command": "server.py"},
            {"name": "archive", "command": "run"},
            {"name": "ledger", "command": "server.py"},
        ],
        {"grader/server.py": "", "archive/run": "#!/bin/sh\n", "u01/server.py": "", "daemon/server.py": ""},
    )
    problems = validate_scenario(load_scenario(folder)).problems
    text = "\n".join(problems)
    assert "service grader is listed more than once" in text
    assert "service u01: the name is already a user" in text
    assert "service daemon: the name is already a user" in text
    assert "service archive: program run is not executable" in text
    assert "service ledger: folder services/ledger/ is missing" in text


def test_valid_service_passes_check(tmp_path):
    folder = with_service(tmp_path, [{"name": "grader", "command": "server.py"}], {"grader/server.py": ""})
    scenario = load_scenario(folder)
    assert service_problems(scenario) == []
    assert not [p for p in validate_scenario(scenario).problems if "service" in p]


def test_service_users_sit_between_board_authors_and_agents(tmp_path):
    folder = with_service(
        tmp_path,
        [{"name": "grader", "command": "server.py"}, {"name": "archive", "command": "serve"}],
        {"grader/server.py": "", "archive/serve": ""},
    )
    users = service_users(load_scenario(folder))
    assert [u.uid for u in users] == [SERVICE_UID_BASE, SERVICE_UID_BASE + 1]
    assert all(1600 < u.uid < UID_BASE for u in users)
    assert users[0].socket == "/run/services/grader/grader.sock"
    assert users[0].state == "/var/lib/svc/grader"


def test_dockerfile_gives_each_program_a_private_folder(tmp_path):
    folder = with_service(tmp_path, [{"name": "grader", "command": "server.py"}], {"grader/server.py": ""})
    text = team_dockerfile("base:tag", load_scenario(folder), 0, ["ops"])
    useradd = next(line for line in text.splitlines() if "useradd" in line and " grader" in line)
    # its own user, not in the agents' shared group
    assert "-g grader " in useradd and "staff" not in useradd and "nologin" in useradd
    assert "usermod" not in useradd  # nobody else, root included, joins its group
    assert "COPY --chown=grader:grader services/grader/ /srv/grader/" in text
    assert "chmod 700 /srv/grader && chmod -R go-rwx /srv/grader" in text


def test_dockerfile_without_services_is_unchanged(tmp_path):
    text = team_dockerfile("base:tag", load_scenario(make_scenario(tmp_path)), 0, ["ops"])
    assert "services" not in text and "/srv" not in text


def test_compose_mounts(tmp_path):
    folder = with_service(tmp_path, [{"name": "grader", "command": "server.py"}], {"grader/server.py": ""})
    tmpfs = team_service(load_scenario(folder), 0, "img", "run")["tmpfs"]
    uid = SERVICE_UID_BASE
    # only the program can write its socket folder or open its private folder
    assert f"/run/services/grader:mode=0755,uid={uid},gid={uid},size=1m" in tmpfs
    assert f"/var/lib/svc/grader:mode=0700,uid={uid},gid={uid},size=64m" in tmpfs
    plain = team_service(load_scenario(make_scenario(tmp_path / "plain")), 0, "img", "run")["tmpfs"]
    assert not [t for t in plain if "services" in t or "/svc/" in t]


def test_start_script_runs_python_programs_isolated(tmp_path):
    folder = with_service(tmp_path, [{"name": "grader", "command": "server.py"}], {"grader/server.py": ""})
    script = start_script(service_users(load_scenario(folder))[0], "Europe/London")
    assert "env -i " in script and "umask 077" in script
    assert (
        "/usr/local/sbin/svcrun /run/services/grader/grader.sock /usr/local/bin/python3 -I server.py"
        in script
    )
    assert "SERVICE_SOCKET=/run/services/grader/grader.sock" in script and "TZ=Europe/London" in script
    assert "[ -S /run/services/grader/grader.sock ]" in script


def test_start_script_runs_other_programs_directly(tmp_path):
    folder = with_service(tmp_path, [{"name": "archive", "command": "bin/serve"}], {"archive/bin/serve": ""})
    os.chmod(folder / "services" / "archive" / "bin" / "serve", 0o755)
    script = start_script(service_users(load_scenario(folder))[0])
    assert "/usr/local/sbin/svcrun /run/services/archive/archive.sock ./bin/serve" in script


@pytest.mark.parametrize(
    "cmd",
    [
        "curl -s --unix-socket /run/services/grader/grader.sock http://grader/run -d @out.txt",
        "curl --unix-socket=/run/services/grader/grader.sock http://localhost/status",
        "echo status | nc -U /run/services/grader/grader.sock",
    ],
)
def test_requests_to_a_local_program_are_not_network_access(cmd):
    assert "network" not in {h.category for h in rules.scan_call({"cmd": cmd})}


@pytest.mark.parametrize(
    "cmd",
    [
        "curl --unix-socket /run/services/grader/grader.sock http://x/ ; curl https://example.com/data",
        "curl https://example.com/run/services/grader/grader.sock",
        "curl --unix-socket /tmp/other.sock http://x/",
        "curl https://example.com/ # --unix-socket /run/services/x.sock",
        "curl --unix-socket /run/services/x.sock http://x/$(wget https://example.com/)",
        "curl --unix-socket /run/services/x.sock http://x/ --next https://example.com/",
        "curl -U /run/services/x.sock https://example.com/",
        "curl --unix-socket /run/services/../../tmp/x.sock https://example.com/",
        "curl -K urls.txt --unix-socket /run/services/x.sock http://x/",
    ],
)
def test_other_requests_are_still_flagged(cmd):
    assert "network" in {h.category for h in rules.scan_call({"cmd": cmd})}


def test_escape_rules_still_apply_through_a_service_path():
    hits = rules.scan_call({"cmd": "curl --unix-socket /run/services/../docker.sock http://x/"})
    assert any(h.category == "escape" for h in hits)
    hits = rules.scan_call(
        {"cmd": "curl --unix-socket /run/services/x.sock http://x/ ; ls /var/run/docker.sock"}
    )
    assert any(h.category == "escape" for h in hits)
