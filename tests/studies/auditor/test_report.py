"""Smoke tests for the auditor study's report: figures and Markdown from simulated data."""

from __future__ import annotations

import pytest

from swarmbench.studies.auditor import analysis as an
from swarmbench.studies.auditor import report as rp


def test_report_markdown_without_figures(tmp_path):
    data = rp.simulated_inputs(seed=3)
    path = rp.build_report(
        data["scores"], tmp_path, yardstick=data["yardstick"], queue=data["queue"], n_boot=300, figures=False
    )
    text = path.read_text()
    assert text.startswith("# Auditor prediction study")
    assert "## The six headline results" in text
    for name in an.SITUATION_NAMES.values():
        assert name in text
    assert any(label in text for label in (an.MATCHES, an.MISMATCH, an.CANT_TELL))
    assert (tmp_path / "analysis.json").exists()


def test_report_figures_are_produced(tmp_path):
    pytest.importorskip("matplotlib")
    data = rp.simulated_inputs(seed=3)
    path = rp.build_report(
        data["scores"], tmp_path, yardstick=data["yardstick"], queue=data["queue"], n_boot=300
    )
    text = path.read_text()
    for name in ("headline", "by_scenario", "by_tool_kind", "drift", "paired", "timing_scatter", "queue"):
        assert (tmp_path / f"{name}.png").stat().st_size > 10_000, name
        assert (tmp_path / f"{name}.svg").exists(), name
        assert f"]({name}.png)" in text, name
    assert "95% intervals" in text


def test_formatting_helpers():
    assert rp.pct(0.912) == "91%"
    assert rp.factor(1.234) == "1.23×"
    assert rp.factor(float("inf")) == "∞"
    est, rng = rp.format_part_value({"measure": "difference", "estimate": 0.1, "low": -0.05, "high": 0.2})
    assert (est, rng) == ("+10 points", "-5 to +20 points")


def test_report_has_the_leave_one_out_check(tmp_path):
    data = rp.simulated_inputs(seed=3)
    text = rp.build_report(
        data["scores"], tmp_path, queue=data["queue"], n_boot=200, figures=False
    ).read_text()
    assert "## Does one scenario decide a result?" in text
    assert "Every case equal" in text
    assert "proof conference only" in text


def test_comparison_report(tmp_path):
    pytest.importorskip("matplotlib")
    data = rp.simulated_inputs(seed=3)
    good = data["scores"]
    poor = good.copy()
    poor.loc[poor.index[::3], "hit"] = 0.0
    path = rp.build_comparison(
        {"model A": good, "model B": poor},
        tmp_path,
        yardstick=data["yardstick"],
        n_boot=200,
        timing_headline="within2",
    )
    text = path.read_text()
    assert (
        "## Headline results by model" in text and "## Differences between models on the same cases" in text
    )
    assert "model A − model B" in text
    assert (tmp_path / "models.png").exists()
    assert (tmp_path / "model-a" / "report.md").exists() and (tmp_path / "model-b" / "headline.png").exists()
    single = (tmp_path / "model-a" / "report.md").read_text()
    assert "within 2×" in single and "## Timing by how long commands really took" in single
