"""Image packaging for scripted events: the participant user and the private event files."""

from __future__ import annotations

from pathlib import Path

from swarmbench.config import load_scenario
from swarmbench.engine.events import (
    copy_event_trees,
    event_problems,
    event_script_rel,
    event_source_folder,
)
from swarmbench.engine.image import _copy_tree, team_dockerfile
from swarmbench.engine.layout import participant_users


def _scenario(tmp_path: Path, *, run="events/plant/run.py", make_script=True, agents=3):
    (tmp_path / "scenario.yaml").write_text(
        "name: x\ntime_limit: 90m\n"
        f"swarm: {{agents: {agents}}}\n"
        "advanced:\n  events:\n"
        f"    - {{name: plant, as_user: u31, run: {run}}}\n"
    )
    (tmp_path / "prompt.md").write_text("Do the work.\n")
    (tmp_path / "workspace").mkdir(exist_ok=True)
    folder = tmp_path / "events" / "plant"
    folder.mkdir(parents=True, exist_ok=True)
    if make_script:
        rel = run.split("/", 2)[2]
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text("print('hi')\n")
        (folder / "payload").mkdir(exist_ok=True)
        (folder / "payload" / "p.lean").write_text("theorem t : True := by trivial\n")
    return load_scenario(tmp_path)


def test_participant_user_and_uid(tmp_path):
    s = _scenario(tmp_path)
    (p,) = participant_users(s)
    assert p.user == "u31" and p.events == ("plant",)
    # u31 is the next participant number after agents u01..u03 (uid base 2000)
    assert p.uid == 2031
    assert p.folder == "/var/lib/sched/u31" and p.event_folder("plant") == "/var/lib/sched/u31/e1"


def test_dockerfile_creates_a_private_nologin_participant(tmp_path):
    s = _scenario(tmp_path)
    df = team_dockerfile("base:tag", s, 0, ["ops"])
    assert "useradd -M -d /var/lib/sched/u31 -u 2031 -g u31 -G staff -s /usr/sbin/nologin u31" in df
    assert "COPY --chown=u31:u31 events/u31/e1/ /var/lib/sched/u31/e1/" in df
    # owned by the participant and private to it: no read or search for group/other
    assert "chown -R u31:u31 /var/lib/sched/u31 && chmod -R u=rwX,go= /var/lib/sched/u31" in df


def test_copy_event_trees_lays_out_the_script_and_payload(tmp_path):
    s = _scenario(tmp_path)
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    copy_event_trees(s, 0, ctx, _copy_tree)
    assert (ctx / "events" / "u31" / "e1" / "run.py").read_text() == "print('hi')\n"
    assert (ctx / "events" / "u31" / "e1" / "payload" / "p.lean").is_file()


def test_event_folder_and_script_rel(tmp_path):
    s = _scenario(tmp_path, run="events/plant/bin/go.sh")
    (ev,) = s.advanced.events
    assert event_source_folder(s, ev) == tmp_path / "events" / "plant"
    assert event_script_rel(ev) == "bin/go.sh"


def test_event_problems_reports_a_missing_script(tmp_path):
    s = _scenario(tmp_path, make_script=False)
    problems = event_problems(s)
    assert problems and "plant" in problems[0]
