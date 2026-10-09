"""Everything the two-pass judge reads for one sample, built deterministically
(docs/judge-two-pass.md, build stage 1): the ledger, its compacted view, the
workspace evidence, and an empty coverage manifest for the judge calls to fill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from inspect_ai.log import EvalSample

from swarmbench.judge.compaction import Compacted, compact, policy_for
from swarmbench.judge.evidence import WorkspaceEvidence, link_file_references, workspace_evidence
from swarmbench.judge.extract import SampleInputs
from swarmbench.judge.ledger import Ledger, build_ledger
from swarmbench.judge.manifest import Manifest


@dataclass
class Material:
    ledger: Ledger
    view: list[Compacted]
    workspace: WorkspaceEvidence
    manifest: Manifest
    problems: list[str] = field(default_factory=list)
    """Source-inventory problems found while building (log events with no ledger entry or reason)."""


def build_material(sample: EvalSample, inputs: SampleInputs, run_root: Path | None) -> Material:
    """The sample must be read with attachments resolved."""
    ledger = build_ledger(sample, inputs)
    workspace = workspace_evidence(run_root, inputs.workspace_changes, inputs.workspace_gaps,
                                   inputs.workspace_total)
    link_file_references(ledger, workspace)
    unaccounted = ledger.unaccounted(sample)
    problems = list(ledger.problems)
    if unaccounted:
        problems.append(f"{len(unaccounted)} log events were neither put in the ledger nor explained")
    view = compact(ledger, policy_for(inputs, workspace))
    return Material(ledger=ledger, view=view, workspace=workspace, manifest=Manifest(ledger),
                    problems=problems)
