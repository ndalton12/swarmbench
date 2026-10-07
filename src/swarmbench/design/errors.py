"""The designer's one error type."""

from __future__ import annotations


class DesignError(RuntimeError):
    """The designer could not produce a valid scenario (or could not start)."""

    def __init__(self, message: str, errors: list[str], last_reply: str = ""):
        super().__init__(message + "".join(f"\n- {e}" for e in errors))
        self.errors = errors
        self.last_reply = last_reply
