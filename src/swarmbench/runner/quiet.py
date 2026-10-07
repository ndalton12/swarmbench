"""Keep library chatter out of the terminal.

Docker Compose, Inspect and Scout print progress and warnings of their own. While a run or
the judge works in the foreground, everything written to stdout and stderr (by Python code
and by child processes) goes to the run's log file instead, and our own progress lines go
to the real terminal.
"""

from __future__ import annotations

import io
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO


def _fd(stream: TextIO) -> int | None:
    try:
        return stream.fileno()
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        return None


@contextmanager
def output_to(log_file: Path) -> Iterator[TextIO]:
    """Send all output to ``log_file`` for the duration; yield a stream to the real terminal."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    saved_out, saved_err = os.dup(1), os.dup(2)
    # The terminal: a copy of the original stdout, unless stdout isn't a real file
    # (as under a test runner), in which case the original object itself.
    terminal: TextIO
    if _fd(old_stdout) == 1:
        terminal = os.fdopen(os.dup(saved_out), "w", buffering=1)
        own_terminal = True
    else:
        terminal, own_terminal = old_stdout, False
    log = open(log_file, "a", buffering=1)  # noqa: SIM115 - closed in finally
    try:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        sys.stdout = sys.stderr = log
        yield terminal
    finally:
        log.flush()
        sys.stdout, sys.stderr = old_stdout, old_stderr
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        log.close()
        if own_terminal:
            terminal.close()


@contextmanager
def passthrough() -> Iterator[TextIO]:
    """The ``--verbose`` alternative: leave output alone."""
    yield sys.stdout
