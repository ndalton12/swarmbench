"""Date placeholders in scenario files, rendered relative to the run start."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from swarmbench.design import check_dates, render_dates, seed_workspace
from swarmbench.design.checks import validate
from tests.design.conftest import NOTES, PROMPT, SCENARIO_YAML

BERLIN = ZoneInfo("Europe/Berlin")
# A Wednesday afternoon.
NOW = datetime(2026, 10, 7, 15, 30, tzinfo=BERLIN)


def test_render_offsets_units_and_formats() -> None:
    assert render_dates("{{date:-3d 16:02}}", NOW) == "2026-10-04T16:02:00+02:00"
    assert render_dates("{{date:-36h}}", NOW) == "2026-10-06T03:30:00+02:00"
    assert render_dates("{{date:+2wd|weekday}}", NOW) == "Friday"
    assert render_dates("{{date:+3wd|weekday}}", NOW) == "Monday"  # skips the weekend
    assert render_dates("{{date:-3wd|date}}", NOW) == "2026-10-02"  # Friday before
    assert render_dates("{{date:0d 08:30|time}}", NOW) == "08:30"
    assert render_dates("Date: {{date:-2wd 09:14|rfc2822}}", NOW) == "Date: Mon, 05 Oct 2026 09:14:00 +0200"
    assert (
        render_dates("{{date:-1d|%d/%m/%Y}} and no placeholder {{other}}", NOW)
        == "06/10/2026 and no placeholder {{other}}"
    )


def test_check_reports_bad_placeholders() -> None:
    assert check_dates("{{date:-2wd 09:14|rfc2822}} {{date:+1d|%A}}") == []
    assert check_dates("{{date:fri-3d}}")
    assert check_dates("{{date:-2w}}")
    assert check_dates("{{date:}}")
    assert check_dates("{{date:-1d|fancy}}")


def test_validation_sends_bad_placeholders_for_repair() -> None:
    files = {
        "scenario.yaml": SCENARIO_YAML,
        "prompt.md": PROMPT,
        "notes.md": NOTES,
        "workspace/mail/freeze.eml": "Date: {{date:last tuesday}}\n",
    }
    errors = validate(files).errors
    assert any(e.startswith("workspace/mail/freeze.eml: bad date placeholder") for e in errors)


def test_seed_renders_dates_in_files_and_history(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario"
    files = {
        "workspace/mail/freeze.eml": "Date: {{date:-2wd 09:14|rfc2822}}\n\nfreeze is {{date:+2wd|weekday}}\n",
        "workspace/README.md": "updated {{date:-1d|date}}\n",
        "history/c01/README.md": "first draft {{date:-9d|date}}\n",
        "history.yaml": (
            "timezone: Europe/Berlin\ncommits:\n"
            '  - date: "-9d 10:00"\n    author: "Ana Brandt <abrandt@halden-labs.com>"\n'
            "    message: readme\n    files: {README.md: history/c01/README.md}\n"
            '  - date: "-1d 11:00"\n    author: "Ana Brandt <abrandt@halden-labs.com>"\n'
            "    message: update readme\n    files: {README.md: workspace/README.md}\n"
        ),
    }
    for rel, text in files.items():
        (scenario / rel).parent.mkdir(parents=True, exist_ok=True)
        (scenario / rel).write_text(text)
    dest = tmp_path / "volume"
    assert seed_workspace(scenario, "workspace", dest, now=NOW, seed=0)

    assert (
        dest / "mail/freeze.eml"
    ).read_text() == "Date: Mon, 05 Oct 2026 09:14:00 +0200\n\nfreeze is Friday\n"
    assert (dest / "README.md").read_text() == "updated 2026-10-06\n"
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=dest, env=env, check=True, capture_output=True, text=True
        ).stdout

    first = git("log", "--reverse", "--format=%H").split()[0]
    assert git("show", f"{first}:README.md") == "first draft 2026-09-28\n"
    assert git("status", "--porcelain") == ""
