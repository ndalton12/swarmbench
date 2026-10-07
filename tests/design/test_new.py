"""new_scenario: drafting, repair, realism review and never overwriting."""

from __future__ import annotations

from pathlib import Path

import pytest
from inspect_ai.model import ModelOutput

from swarmbench.config import load_scenario
from swarmbench.design import DesignError, new_scenario
from tests.design.conftest import NOTES, PROMPT, SCENARIO_YAML, Script, block, good_scenario_reply

CRITIQUE = (
    "<critique>\n1. workspace/recon/README.md: too tidy, reads like a briefing. Rewrote it in the "
    "voice of the analyst who set it up.\n</critique>\n"
    + block("workspace/recon/README.md", "recon scripts, mostly mine (tl). `make recon` still works i think")
    + "<done/>"
)


def run_new(tmp_path: Path, script: Script, **kwargs) -> tuple[Path, list[str]]:
    printed: list[str] = []
    kwargs.setdefault("scenarios_dir", tmp_path / "scenarios")
    kwargs.setdefault("checklist", tmp_path / "missing_realism.md")
    out = new_scenario(
        "a finance team reconciles a ledger", model=script.model, echo=printed.append, **kwargs
    )
    return out, printed


def test_draft_then_realism_review(tmp_path: Path) -> None:
    script = Script([good_scenario_reply(), CRITIQUE])
    out, printed = run_new(tmp_path, script)

    assert out == tmp_path / "scenarios" / "ledger_reconcile"
    scenario = load_scenario(out)
    assert scenario.name == "ledger-reconcile"
    assert scenario.swarm.agents == 3
    # The review's revision was applied on top of the draft.
    assert "mostly mine (tl)" in (out / "workspace/recon/README.md").read_text()
    assert (out / "workspace/recon/bank_q3.csv").exists()
    log = (out / "design_log.md").read_text()
    assert "too tidy" in log and "a finance team reconciles a ledger" in log
    # The review saw the visible files and the hidden notes, separately.
    assert "Files the agents can see" in script.inputs[1]
    assert "## The honest path" in script.inputs[1]
    # A plain summary for the user.
    summary = printed[0]
    assert "Created a new scenario 'ledger-reconcile'" in summary
    assert "too tidy" in summary
    assert "swarm check" in summary
    assert script.calls == 2


def test_prompt_is_grounded_in_checklist_schema_and_examples(tmp_path: Path, make_scenario) -> None:
    make_scenario("old_example")
    checklist = tmp_path / "realism.md"
    checklist.write_text("# Realism checklist\n- UNIQUE-RULE-7: never use round numbers\n")
    script = Script([good_scenario_reply()])
    run_new(tmp_path, script, checklist=checklist, critique=False, out_dir=tmp_path / "out")
    sent = script.inputs[0]
    assert "UNIQUE-RULE-7" in sent  # the realism checklist
    assert "token_budget" in sent and "encounter:" in sent  # the schema guide
    assert '<example name="old_example">' in sent  # existing scenarios as examples
    assert "a finance team reconciles a ledger" in sent


def test_repair_loop_fixes_invalid_draft(tmp_path: Path) -> None:
    bad = (
        block("scenario.yaml", "name: ledger-reconcile\nswarm:\n  agentz: 3\n")
        + block("prompt.md", PROMPT)
        + "<done/>"
    )
    fix = block("scenario.yaml", SCENARIO_YAML) + block("notes.md", NOTES)
    fix += block("workspace/recon/README.md", "readme") + "<done/>"
    script = Script([bad, fix])
    out, printed = run_new(tmp_path, script, critique=False)

    repair_message = script.inputs[1]
    assert "agentz" in repair_message  # the schema error was sent back
    assert "notes file notes.md is missing or empty" in repair_message
    assert "workspace folder workspace/" in repair_message
    assert load_scenario(out).swarm.agents == 3
    assert "1 repair round" in printed[0]
    assert "agentz" in (out / "design_log.md").read_text()


def test_unparseable_reply_is_repaired(tmp_path: Path) -> None:
    script = Script(["Sure! Here's a great scenario idea: ...", good_scenario_reply()])
    out, _ = run_new(tmp_path, script, critique=False)
    assert "scenario.yaml is missing" in script.inputs[1]
    assert load_scenario(out).name == "ledger-reconcile"


def test_gives_up_after_repairs_and_writes_nothing(tmp_path: Path) -> None:
    bad = block("scenario.yaml", "name: [not, valid") + "<done/>"
    script = Script([bad] * 4)
    with pytest.raises(DesignError) as err:
        run_new(tmp_path, script, critique=False)
    assert "not valid YAML" in str(err.value)
    assert script.calls == 4  # one draft plus three repairs
    assert not (tmp_path / "scenarios").exists()


def test_paths_outside_the_folder_are_never_written(tmp_path: Path) -> None:
    evil = (
        good_scenario_reply().replace("<done/>", "")
        + block("../escaped.txt", "x")
        + block("/tmp/abs_escape.txt", "x")
        + block("workspace/.git/config", "x")
        + '<delete path="../../important"/>'
        + "<done/>"
    )
    script = Script([evil, good_scenario_reply()])
    out, _ = run_new(tmp_path, script, critique=False, out_dir=tmp_path / "out" / "s")
    assert not (tmp_path / "out" / "escaped.txt").exists()
    assert not (tmp_path / "escaped.txt").exists()
    assert not Path("/tmp/abs_escape.txt").exists()
    assert not (out / "workspace/.git").exists()
    repair = script.inputs[1]
    assert "../escaped.txt" in repair and "must be relative" in repair
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert all(p.startswith("out/s/") for p in written)


def test_never_overwrites_an_existing_folder(tmp_path: Path) -> None:
    existing = tmp_path / "taken"
    existing.mkdir()
    (existing / "keep.txt").write_text("mine")
    script = Script([])
    with pytest.raises(FileExistsError):
        run_new(tmp_path, script, out_dir=existing)
    assert script.calls == 0  # refused before spending anything
    assert (existing / "keep.txt").read_text() == "mine"


def test_default_name_picks_a_free_folder(tmp_path: Path, make_scenario) -> None:
    first = make_scenario("ledger_reconcile")
    original = (first / "prompt.md").read_text()
    script = Script([good_scenario_reply()])
    out, _ = run_new(tmp_path, script, critique=False)
    assert out == tmp_path / "scenarios" / "ledger_reconcile_2"
    assert (first / "prompt.md").read_text() == original


def test_failed_review_keeps_the_valid_draft(tmp_path: Path) -> None:
    broken_revision = (
        "<critique>1. ...</critique>\n" + block("scenario.yaml", "name: x\nbogus: 1") + "<done/>"
    )
    script = Script([good_scenario_reply(), *[broken_revision] * 4])
    out, printed = run_new(tmp_path, script)
    assert load_scenario(out).name == "ledger-reconcile"
    assert "first draft was kept" in printed[0]
    assert "first draft was kept" in (out / "design_log.md").read_text()


def test_cut_off_reply_is_continued(tmp_path: Path) -> None:
    whole = good_scenario_reply()
    cut_at = whole.index("bank_q3.csv") + 40
    first = ModelOutput.from_content("mockllm/model", whole[:cut_at], stop_reason="max_tokens")
    rest = block("workspace/recon/bank_q3.csv", "date,amount,ref\n") + "<done/>"
    script = Script([first, rest])
    out, _ = run_new(tmp_path, script, critique=False)
    assert "cut off" in script.inputs[1]
    assert (out / "workspace/recon/bank_q3.csv").read_text() == "date,amount,ref\n"


def test_word_check_warnings_reach_review_and_summary(tmp_path: Path) -> None:
    reply = good_scenario_reply(readme="This sandbox holds the recon scripts.")
    script = Script([reply, "<critique>none</critique><done/>"])
    _out, printed = run_new(tmp_path, script)
    assert "mentions 'sandbox'" in script.inputs[1]
    assert "mentions 'sandbox'" in printed[0]
