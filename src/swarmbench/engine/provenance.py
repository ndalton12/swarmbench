"""provenance.json: what exactly was run, so reruns stay interpretable."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from swarmbench.config import Scenario
from swarmbench.paths import RunDir

from .image import DOCKER_DIR, image_digest


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    if root.is_file():
        return {root.name: _sha256_file(root)}
    return {str(p.relative_to(root)): _sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def _pkg(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _cli_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    agents = DOCKER_DIR / "agents"
    for name in ("claude", "codex"):
        marker = agents / f"{name}.version"
        out[name] = marker.read_text().strip() if marker.exists() else None
    return out


def provenance(scenario: Scenario, images: list[str]) -> dict[str, Any]:
    teams = scenario.resolved_teams()
    prompts = {}
    workspaces = {}
    if scenario.root is not None:
        for t in teams:
            prompts[t.name] = (
                _sha256_file(scenario.path(t.prompt)) if scenario.path(t.prompt).exists() else None
            )
            if t.workspace:
                workspaces[t.name] = _sha256_tree(scenario.path(t.workspace))
    protected = scenario.protected_dir()
    git_rev = None
    try:
        git_rev = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent,
                timeout=10,
            ).stdout.strip()
            or None
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "scenario": scenario.name,
        "config": scenario.model_dump(mode="json"),
        "prompt_sha256": prompts,
        "workspace_sha256": workspaces,
        "protected_sha256": _sha256_tree(protected) if protected else {},
        "images": [{"tag": tag, "id": image_digest(tag)} for tag in images],
        "versions": {
            "inspect_ai": _pkg("inspect-ai"),
            "inspect_swe": _pkg("inspect-swe"),
            "inspect_scout": _pkg("inspect-scout"),
            "swarmbench": _pkg("swarmbench"),
            "swarmbench_git": git_rev,
            "python": platform.python_version(),
            **{f"{k}_cli": v for k, v in _cli_versions().items()},
        },
        "monitor": {
            "model": scenario.advanced.monitor_model,
            "stop_on": scenario.advanced.monitor_stop_on,
        },
        "judge": {"model": scenario.advanced.judge_model, "scanners": scenario.advanced.scanners},
    }


def write_provenance(scenario: Scenario, run_dir: RunDir, images: list[str]) -> Path:
    run_dir.provenance.write_text(json.dumps(provenance(scenario, images), indent=2))
    return run_dir.provenance
