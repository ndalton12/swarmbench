"""Judge: Inspect Scout scanners plus a plain-language summarizer.

Owned by the observer teammate. See docs/interfaces.md section 6.
"""

from __future__ import annotations

from swarmbench.paths import RunDir
from swarmbench.types import JudgeReport


def judge_run(run_dir: RunDir, model: str | None = None) -> list[JudgeReport]:
    raise NotImplementedError
