"""Keeping the judge blind to which agent runs which model, when a run mixes models.

The run brief leaves models out, and the text the judge reads (the ledger) has each agent
model's name replaced by ``[model]``: the full id, its last part, and that part with spaces for
dashes (``openrouter/google/gemini-4-argon``, ``gemini-4-argon``, ``gemini 4 argon``). Agents
can still give themselves away in their own words (a style, a self-description), so this
removes the plain labels, not every clue.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

MASK = "[model]"


def mixed_models(agents_meta: list[dict[str, Any]]) -> dict[str, str]:
    """Agent name -> model, when the run's agents use more than one model (else empty)."""
    models = {str(a["name"]): str(a["model"]) for a in agents_meta if a.get("name") and a.get("model")}
    return models if len(set(models.values())) > 1 else {}


def models_note(agents_meta: list[dict[str, Any]]) -> str | None:
    """For the report: which agent ran which model, when the judge wasn't told."""
    models = mixed_models(agents_meta)
    if not models:
        return None
    pairs = "; ".join(f"{name}: {model}" for name, model in models.items())
    return (
        "Models (the judge read without them: left out of its brief and masked in the text it "
        f"read, though agents' own words may still hint): {pairs}"
    )


def redactor(agents_meta: list[dict[str, Any]]) -> Callable[[str], str] | None:
    """A function masking the agents' model names in text, or None when nothing needs masking."""
    names: set[str] = set()
    for model in set(mixed_models(agents_meta).values()):
        last = model.rsplit("/", 1)[-1]
        names |= {model, last, last.replace("-", " ")}
    names = {n for n in names if len(n) >= 4}
    if not names:
        return None
    # longest first, so a full id is masked whole rather than leaving its provider prefix
    pattern = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)), re.IGNORECASE)
    return lambda text: pattern.sub(MASK, text) if text else text
