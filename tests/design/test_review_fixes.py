"""Regression tests for problems found in code review."""

from __future__ import annotations

import itertools
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


# --- second review round ---------------------------------------------------------------


@pytest.mark.parametrize("yaml_extra", ["workspace: /etc\n", "protected: /opt/secrets\n"])
def test_absolute_folder_references_are_rejected(yaml_extra: str) -> None:
    files = base_files()
    files["scenario.yaml"] = SCENARIO_YAML + yaml_extra
    errors = validate(files).errors
    assert any("must be relative" in e for e in errors), errors


def test_hour_offsets_count_real_hours_across_dst() -> None:
    from swarmbench.design import render_dates

    berlin = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 3, 29, 3, 30, tzinfo=berlin)  # just after clocks went forward
    assert render_dates("{{date:-1h}}", now) == "2026-03-29T01:30:00+01:00"
    # 02:15 doesn't exist that day; it becomes a real time.
    assert render_dates("{{date:0d 02:15}}", now) == "2026-03-29T03:15:00+02:00"


def test_commit_times_stay_before_run_start_across_dst(tmp_path: Path) -> None:
    from swarmbench.design.history import _Commit, _commit_times

    berlin = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 3, 29, 3, 10, tzinfo=berlin)
    mk = lambda days, h, m: _Commit(days, h, m, "a", "a@b", "m", "main", None, {})
    commits = [mk(2, 10, 0), mk(1, 9, 45), mk(0, 2, 59), mk(0, 23, 0)]
    import random

    times = _commit_times(commits, now, random.Random(0))
    assert all(a < b for a, b in itertools.pairwise(times))
    assert max(times) <= now - timedelta(minutes=20)
    # Only the late commits moved; the early ones kept their written day and time (plus jitter).
    assert abs(times[1] - datetime(2026, 3, 28, 9, 45, tzinfo=berlin)) < timedelta(minutes=8)


def test_redundant_merges_are_rejected() -> None:
    files = {"workspace/a.txt": "a\n"}
    redundant = history(
        commit("-9d 10:00", "{a.txt: workspace/a.txt}"),
        commit("-8d 10:00", "{}", "    branch: feat\n"),
        commit("-7d 10:00", "{}", "    merge: feat\n"),
        commit("-6d 10:00", "{}", "    merge: feat\n"),
    )
    assert any("already merged" in e for e in check_history(redundant, files))


def test_criss_cross_detected() -> None:
    from swarmbench.design.history import _merge_bases

    # 0 <- 1 (main), 0 <- 2 (feat); 3 = merge(1, 2) on main; 4 = merge(2, 1) on feat
    parents = [[], [0], [0], [1, 2], [2, 1]]
    assert _merge_bases(parents, 3, 4) == [1, 2]
    assert _merge_bases(parents, 1, 2) == [0]


def test_publish_never_replaces_a_folder_that_appears(tmp_path: Path, monkeypatch) -> None:
    import shutil as real_shutil

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "f.txt").write_text("x")
    target = tmp_path / "pub" / "scenario"
    original_copytree = real_shutil.copytree

    def copy_then_intrude(src, dst, **kw):
        result = original_copytree(src, dst, **kw)
        (target / "someone_elses.txt").write_text("keep me")
        return result

    monkeypatch.setattr("swarmbench.design.folder.shutil.copytree", copy_then_intrude)
    with pytest.raises(OSError):
        publish(staging, target)
    assert (target / "someone_elses.txt").read_text() == "keep me"
    assert not (target / "f.txt").exists()
    assert [p.name for p in (tmp_path / "pub").iterdir()] == ["scenario"]


def test_deleting_a_folder_clears_cut_off_files_beneath_it(tmp_path: Path) -> None:
    first = good_scenario_reply().replace("<done/>", "") + '<file path="workspace/old/a.txt">\nhalf'
    script = Script([first, '<delete path="workspace/old"/><done/>'])
    out = new_scenario(
        "x",
        out_dir=tmp_path / "o",
        model=script.model,
        critique=False,
        echo=None,
        checklist=tmp_path / "none.md",
    )
    assert not (out / "workspace/old").exists()
    assert script.calls == 2
