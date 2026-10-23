"""Lower-case the type names in the tool declarations a Gemini client sends through the bridge.

The Antigravity SDK declares an agent's own Python tools (``LocalAgentConfig(tools=...)``) in
Gemini's schema dialect, with upper-case type names (``"OBJECT"``, ``"STRING"``). Inspect's
bridge validates each declaration's parameters as JSON Schema, which only accepts lower-case
type names, so every request carrying such a tool fails with HTTP 400 and the agent crashes at
its first turn. Inspect already lower-cases these names for response schemas
(``_google_schema_to_json_schema``) but not for tool declarations (inspect_ai 0.3.277–0.3.283).

``tools_from_google_tools`` is a module-level name looked up at call time, so replacing it is
enough; if a future Inspect moves it, ``install`` does nothing and requests behave as before.
"""

from __future__ import annotations

from typing import Any

_installed = False
_PARAMETER_KEYS = ("parameters", "parametersJsonSchema")


_SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "definitions")
"""Keywords whose value maps names to schemas."""
_SCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
"""Keywords whose value is a list of schemas."""
_SCHEMAS = ("items", "additionalProperties", "not", "contains", "if", "then", "else")
"""Keywords whose value is one schema (``items`` may also be a list of them)."""


def lowercase_types(schema: Any) -> Any:
    """The schema with every ``type`` name (a string, or a list of them) in lower case.

    Only schema keywords are followed, so literal data (``default``, ``enum``, ``examples``...)
    is left as it is, even where it has a key named ``type``."""
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    kind = schema.get("type")
    if isinstance(kind, str):
        out["type"] = kind.lower()
    elif isinstance(kind, list):
        out["type"] = [t.lower() if isinstance(t, str) else t for t in kind]
    for key in _SCHEMA_MAPS:
        if isinstance(schema.get(key), dict):
            out[key] = {name: lowercase_types(sub) for name, sub in schema[key].items()}
    for key in _SCHEMA_LISTS:
        if isinstance(schema.get(key), list):
            out[key] = [lowercase_types(sub) for sub in schema[key]]
    for key in _SCHEMAS:
        value = schema.get(key)
        if isinstance(value, list):
            out[key] = [lowercase_types(sub) for sub in value]
        elif isinstance(value, dict):
            out[key] = lowercase_types(value)
    return out


def normalise_google_tools(google_tools: Any) -> Any:
    """Gemini ``tools`` with each function declaration's parameter types lower-cased."""
    if not isinstance(google_tools, list):
        return google_tools
    out = []
    for tool in google_tools:
        declarations = tool.get("functionDeclarations") if isinstance(tool, dict) else None
        if isinstance(declarations, list):
            tool = {
                **tool,
                "functionDeclarations": [
                    {k: (lowercase_types(v) if k in _PARAMETER_KEYS else v) for k, v in d.items()}
                    if isinstance(d, dict)
                    else d
                    for d in declarations
                ],
            }
        out.append(tool)
    return out


def install() -> bool:
    """Wrap the bridge's Gemini tool parser (once per process)."""
    global _installed
    if _installed:
        return True
    try:
        from inspect_ai.agent._bridge import google_api_impl
    except ImportError:
        return False
    original = getattr(google_api_impl, "tools_from_google_tools", None)
    if original is None:
        return False

    def wrapped(google_tools: Any, *args: Any, **kwargs: Any) -> Any:
        return original(normalise_google_tools(google_tools), *args, **kwargs)

    google_api_impl.tools_from_google_tools = wrapped
    _installed = True
    return True
