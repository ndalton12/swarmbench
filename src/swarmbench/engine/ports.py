"""Unique bridge ports for inspect-swe agents sharing a container.

Claude Code and Codex each pick their bridge port by reading a counter in the
sample store (``claude_code_model_port`` / ``codex_cli_model_port``, both
starting at 3000) and adding one. With two harnesses in one container they would
collide, so before starting each inspect-swe agent we take a lock, set that
harness's counter to one below the port we want, start the agent, and hold the
lock until the agent has read it.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import anyio
from inspect_ai.util import store

STORE_KEYS = {"claude_code": "claude_code_model_port", "codex_cli": "codex_cli_model_port"}
FIRST_PORT = 3001


class PortAllocator:
    """One per sample. Ports are unique per container across all harnesses.

    The lock is shared by all containers because the store counters are per sample.
    """

    def __init__(self, first: int = FIRST_PORT) -> None:
        self.first = first
        self.next: dict[str, int] = {}
        self.lock = anyio.Lock()

    def reserve(self, sandbox: str) -> int:
        port = self.next.get(sandbox, self.first)
        self.next[sandbox] = port + 1
        return port

    async def start_with_port(
        self,
        port: int,
        harness: str,
        start: Callable[[], None],
        finished: Callable[[], bool],
        timeout: float = 120,
    ) -> int:
        """Start an agent so that its bridge uses ``port`` (from ``reserve``).

        ``start`` launches the agent (e.g. ``task_group.start_soon``); ``finished``
        says whether it has already ended (so a crash before reading the port
        doesn't hold the lock forever).
        """
        key = STORE_KEYS[harness]
        async with self.lock:
            store().set(key, port - 1)
            start()
            deadline = time.monotonic() + timeout
            while store().get(key) != port and not finished():
                if time.monotonic() > deadline:
                    raise RuntimeError(f"agent did not claim bridge port {port} within {timeout}s")
                await anyio.sleep(0.02)
            return port
