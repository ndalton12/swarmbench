"""The loop shared by every design step: ask, apply the reply, validate, repair.

The model's reply is applied on top of a set of files held in memory. Then
the result is validated. Problems go back to the model in the same
conversation until the scenario loads or the repair budget runs out. A reply
cut off at the output limit is continued rather than counted as a repair.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from swarmbench.design.blocks import format_files, parse_reply
from swarmbench.design.checks import CheckResult, validate
from swarmbench.design.folder import UnsafePath, safe_path
from swarmbench.design.llm import Chat
from swarmbench.design.prompts import CONTINUE_REQUEST, repair_request

MAX_REPAIRS = 3
MAX_CONTINUES = 4


class DesignError(RuntimeError):
    """The model could not produce a valid scenario."""

    def __init__(self, message: str, errors: list[str], last_reply: str = ""):
        super().__init__(message + "\n" + "\n".join(f"- {e}" for e in errors))
        self.errors = errors
        self.last_reply = last_reply


@dataclass
class Draft:
    files: dict[str, str]
    binaries: dict[str, bytes]
    check: CheckResult
    replies: list[str] = field(default_factory=list)
    repairs: list[list[str]] = field(default_factory=list)
    """The problems sent back to the model, one list per repair round."""


async def draft_until_valid(
    chat: Chat,
    request: str,
    files: dict[str, str] | None = None,
    binaries: dict[str, bytes] | None = None,
    readonly: set[str] | None = None,
    max_repairs: int = MAX_REPAIRS,
    extra_check: Callable[[dict[str, str]], list[str]] | None = None,
) -> Draft:
    """Ask, apply the reply to ``files``, validate, and repair until it loads."""
    files = dict(files or {})
    binaries = dict(binaries or {})
    readonly = set(readonly or ())
    draft = Draft(files, binaries, CheckResult())
    message = request
    continues = 0
    problems: list[str] = []
    cut: set[str] = set()
    while True:
        reply = await chat.ask(message)
        draft.replies.append(reply)
        new_problems, written, incomplete = apply_reply(reply, files, binaries, readonly)
        problems += new_problems
        cut = {c for c in cut if not any(c == w or c.startswith(w + "/") for w in written)} | incomplete
        if chat.cut_off:
            if continues >= MAX_CONTINUES:
                raise DesignError(
                    f"the reply was still being cut off after {MAX_CONTINUES} continuations",
                    [
                        "the scenario is too large for the model's output limit; ask for fewer or smaller files"
                    ],
                    reply,
                )
            continues += 1
            message = CONTINUE_REQUEST
            continue
        draft.check = validate(files, binaries)
        errors = problems + [f"{p} was cut off before </file>; write it again in full" for p in sorted(cut)]
        errors += draft.check.errors
        if extra_check:
            errors += extra_check(files)
        if not errors:
            return draft
        if len(draft.repairs) >= max_repairs:
            raise DesignError(
                f"the scenario still has problems after {max_repairs} repair attempts", errors, reply
            )
        draft.repairs.append(errors)
        problems = []  # cut-off files stay pending until they are rewritten or deleted
        message = repair_request(errors)


def show_files(files: dict[str, str], per_file: int = 20_000, total: int = 300_000) -> tuple[str, set[str]]:
    """Files formatted for a prompt, and the ones that were too large to show in full."""
    shown: dict[str, str] = {}
    readonly: set[str] = set()
    budget = total
    for path in sorted(files, key=lambda p: (p.count("/"), p)):
        text = files[path]
        limit = min(per_file, max(budget, 0))
        if len(text) > limit:
            readonly.add(path)
            text = text[:limit] + f"\n[... {len(files[path]) - limit} more characters not shown ...]"
        shown[path] = text
        budget -= len(text)
    return format_files(shown, readonly), readonly


def apply_reply(
    reply: str, files: dict[str, str], binaries: dict[str, bytes], readonly: set[str]
) -> tuple[list[str], set[str], set[str]]:
    """Apply file blocks and deletes to ``files`` in place.

    Returns (problems to report back, paths written or deleted, paths cut off before their end).
    """
    parsed = parse_reply(reply)
    problems = []
    written = set()
    for raw in parsed.deletes:
        try:
            path = safe_path(raw.rstrip("/"))
        except UnsafePath as e:
            problems.append(f"delete ignored: {e}")
            continue
        written.add(path)
        removed = [p for p in [*files, *binaries] if p == path or p.startswith(path + "/")]
        for p in removed:
            files.pop(p, None)
            binaries.pop(p, None)
            readonly.discard(p)
    for raw, text in parsed.files.items():
        try:
            path = safe_path(raw)
        except UnsafePath as e:
            problems.append(f"file ignored: {e}")
            continue
        if path in readonly:
            problems.append(f"{path} was shown truncated, so it can't be rewritten; leave it or delete it")
            continue
        binaries.pop(path, None)
        files[path] = text
        written.add(path)
    incomplete = set()
    for raw in parsed.incomplete:
        try:
            incomplete.add(safe_path(raw))
        except UnsafePath:
            problems.append(f"file ignored: {raw!r} is not a usable path")
    return problems, written, incomplete
