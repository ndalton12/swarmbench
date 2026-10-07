"""Regression tests for problems found in code review."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from inspect_ai.model import ModelOutput

from swarmbench.design import DesignError, check_history, new_scenario, seed_workspace
from swarmbench.design.checks import validate
from swarmbench.design.evidence import collect, render
from swarmbench.design.folder import publish
from swarmbench.paths import RunDir
from tests.design.conftest import NOTES, PROMPT, SCENARIO_YAML, Script, block, good_scenario_reply

AUTHOR = '"Ana Brandt <abrandt@halden-labs.com>"'


def history(*commits: str) -> str:
    return "commits:\n" + "".join(commits)


def commit(date: str, files: str, extra: str = "") -> str:
    return f'  - date: "{date}"\n    author: {AUTHOR}\n    message: m\n    files: {files}\n{extra}'


def base_files() -> dict[str, str]:
    return {"scenario.yaml": SCENARIO_YAML, "prompt.md": PROMPT, "notes.md": NOTES, "workspace/a.txt": "a\n"}


# --- history paths and branches -----------------------------------------------------


@pytest.mark.parametrize("bad", ["../victim", ".git/config", "src/.git/hooks/post-commit"])
def test_history_rejects_paths_outside_repo(bad: str) -> None:
    text = history(
        commit("-5d 10:00", f"{{{bad}: workspace/a.txt}}"),
        commit("-4d 10:00", f"{{{bad}: null, a.txt: workspace/a.txt}}"),
    )
    errors = check_history(text, {"workspace/a.txt": "a\n"})
    assert errors, bad


@pytest.mark.parametrize("name", ["feature.lock", "topic..old", "HEAD", "a b", "x~1", ".hidden", "end/"])
def test_history_rejects_bad_branch_names(name: str) -> None:
    text = history(
        commit("-5d 10:00", "{a.txt: workspace/a.txt}"),
        commit("-4d 10:00", "{}", f"    branch: '{name}'\n"),
    )
    assert check_history(text, {"workspace/a.txt": "a\n"})


def test_history_rejects_branch_prefix_collisions() -> None:
    text = history(
        commit("-5d 10:00", "{a.txt: workspace/a.txt}"),
        commit("-4d 10:00", "{}", "    branch: tl\n"),
        commit("-3d 10:00", "{}", "    branch: tl/x\n"),
    )
    assert any("can't both exist" in e for e in check_history(text, {"workspace/a.txt": "a\n"}))


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout


def test_merging_main_into_a_feature_keeps_feature_edits(tmp_path: Path) -> None:
    files = {
        "workspace/a.txt": "a2\n",
        "workspace/b.txt": "b2\n",
        "history/a1": "a1\n",
        "history/b1": "b1\n",
    }
    text = history(
        commit("-9d 10:00", "{a.txt: history/a1, b.txt: history/b1}"),
        commit("-8d 10:00", "{a.txt: workspace/a.txt}", "    branch: feat\n"),
        commit("-7d 10:00", "{b.txt: workspace/b.txt}"),
        commit("-6d 10:00", "{}", "    branch: feat\n    merge: main\n"),
        commit("-5d 10:00", "{}", "    merge: feat\n"),
    )
    assert check_history(text, files) == []
    scenario = tmp_path / "s"
    for rel, content in {**files, "history.yaml": text}.items():
        (scenario / rel).parent.mkdir(parents=True, exist_ok=True)
        (scenario / rel).write_text(content)
    dest = tmp_path / "v"
    seed_workspace(scenario, "workspace", dest, seed=1)
    assert git(dest, "show", "feat:a.txt") == "a2\n"
    assert git(dest, "show", "feat:b.txt") == "b2\n"
    assert git(dest, "status", "--porcelain") == ""


def test_commit_times_never_reach_the_run_start(tmp_path: Path) -> None:
    now = datetime(2026, 10, 7, 9, 0, tzinfo=ZoneInfo("UTC"))
    commits = [commit("-0d 23:00", "{a.txt: workspace/a.txt}" if i == 0 else "{}") for i in range(60)]
    scenario = tmp_path / "s"
    (scenario / "workspace").mkdir(parents=True)
    (scenario / "workspace/a.txt").write_text("a\n")
    (scenario / "history.yaml").write_text(history(*commits))
    seed_workspace(scenario, "workspace", tmp_path / "v", now=now, seed=2)
    stamps = [datetime.fromisoformat(x) for x in git(tmp_path / "v", "log", "--format=%aI").split()]
    assert len(stamps) == 60
    assert max(stamps) <= now - timedelta(minutes=20)
    assert len(set(stamps)) == 60


# --- scenario checks -----------------------------------------------------------------


@pytest.mark.parametrize(
    "yaml_extra", ["prompt: /etc/passwd\n", "notes: ../../notes.md\n", "workspace: ../elsewhere\n"]
)
def test_yaml_references_must_stay_inside(yaml_extra: str) -> None:
    files = base_files()
    files["scenario.yaml"] = SCENARIO_YAML + yaml_extra
    errors = validate(files).errors
    assert any("scenario.yaml:" in e and ("relative" in e or "unsupported" in e) for e in errors), errors


def test_file_and_folder_clash_is_a_repair_message() -> None:
    files = {**base_files(), "workspace/item": "x", "workspace/item/data.txt": "y"}
    errors = validate(files).errors
    assert errors == ["workspace/item is used both as a file and as a folder"]


# --- drafting loop -------------------------------------------------------------------


def test_cut_off_file_stays_pending_until_rewritten(tmp_path: Path) -> None:
    first = good_scenario_reply().replace("<done/>", "") + '<file path="workspace/recon/plan.md">\nhalf'
    script = Script([first, "<done/>", block("workspace/recon/plan.md", "whole plan") + "<done/>"])
    out = new_scenario(
        "x",
        out_dir=tmp_path / "o",
        model=script.model,
        critique=False,
        echo=None,
        checklist=tmp_path / "none.md",
    )
    assert "plan.md was cut off" in script.inputs[1]
    assert "plan.md was cut off" in script.inputs[2]  # still pending after a reply that ignored it
    assert (out / "workspace/recon/plan.md").read_text() == "whole plan\n"


def test_endless_truncation_fails_instead_of_publishing(tmp_path: Path) -> None:
    cut = ModelOutput.from_content("mockllm/model", good_scenario_reply(), stop_reason="max_tokens")
    script = Script([cut] * 5)
    with pytest.raises(DesignError, match="cut off after"):
        new_scenario(
            "x",
            out_dir=tmp_path / "o",
            model=script.model,
            critique=False,
            echo=None,
            checklist=tmp_path / "none.md",
        )
    assert not (tmp_path / "o").exists()


# --- publishing ----------------------------------------------------------------------


def test_publish_leaves_no_partial_folders(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    (staging / "sub").mkdir(parents=True)
    (staging / "sub/f.txt").write_text("x")
    out = publish(staging, tmp_path / "pub" / "scenario")
    assert (out / "sub/f.txt").read_text() == "x"
    assert [p.name for p in (tmp_path / "pub").iterdir()] == ["scenario"]
    assert oct(out.stat().st_mode & 0o777) == "0o755"
    with pytest.raises(FileExistsError):
        publish(staging, out)
    assert [p.name for p in (tmp_path / "pub").iterdir()] == ["scenario"]


# --- evidence ------------------------------------------------------------------------


def test_evidence_tolerates_odd_shapes_and_flags_incomplete_scans(tmp_path: Path) -> None:
    run = RunDir(tmp_path / "run")
    run.root.mkdir()
    run.scenario.write_text("- just\n- a list\n")
    run.report_json.write_text("[]")
    (run.scans / "a").mkdir(parents=True)
    (run.scans / "a/_summary.json").write_text(json.dumps({"scanners": {"x": "bad"}}))
    (run.scans / "b").mkdir(parents=True)
    (run.scans / "b/_summary.json").write_text(
        json.dumps({"complete": False, "scanners": {"deception": {"scans": 2, "results": 0, "errors": 0}}})
    )
    ev = collect(run)
    text = render(ev)
    assert "report.json holds no reports" in text
    assert "unreadable scanner summary scans/a/_summary.json" in text
    assert "did not finish" in text
    assert "deception: 0/2" in text
