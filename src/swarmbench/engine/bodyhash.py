"""The digest of each bridged request body, as the bridge received it.

The container's gateway logs every request with ``body_json_sha256``: the body parsed as
JSON and re-serialised canonically. Here the same digest is computed on the host for the
request the bridge actually handles, and made available to the bridge filter (same task),
which puts it on the ``swarm.attribution`` event. The two records then join exactly.

This wraps the three request entry points the bridge's model service calls. They are
module-level names looked up at call time (inspect_ai 0.3.277), so replacing them is
enough; if a future Inspect moves them, ``install`` does nothing and the digest is None,
which the join reports as unmatched (never guessed).
"""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from typing import Any

_body_hash: ContextVar[str | None] = ContextVar("swarmbench_body_hash", default=None)
_installed = False

_ENTRY_POINTS = (
    "inspect_anthropic_api_request",
    "inspect_responses_api_request",
    "inspect_completions_api_request",
)


def canonical_json_sha256(data: Any) -> str:
    """Same canonical form as the gateway: sorted keys, no spaces, UTF-8."""
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def current_body_hash() -> str | None:
    return _body_hash.get()


def install() -> bool:
    """Wrap the bridge service's request entry points (once per process)."""
    global _installed
    if _installed:
        return True
    try:
        from inspect_ai.agent._bridge.sandbox import service
    except ImportError:
        return False
    for name in _ENTRY_POINTS:
        original = getattr(service, name, None)
        if original is None:
            continue

        def make(original: Any) -> Any:
            async def wrapped(json_data: Any, *args: Any, **kwargs: Any) -> Any:
                try:
                    digest = canonical_json_sha256(json_data)
                except (TypeError, ValueError):
                    digest = None
                token = _body_hash.set(digest)
                try:
                    return await original(json_data, *args, **kwargs)
                finally:
                    _body_hash.reset(token)

            return wrapped

        setattr(service, name, make(original))
    _installed = True
    return True
