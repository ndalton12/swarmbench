"""Model prices from OpenRouter's public model list, saved in a local cache.

OpenRouter publishes prices for several hundred models from every major provider at
https://openrouter.ai/api/v1/models (no key needed). swarmbench saves the list, converted to
dollars per million tokens, in a cache file and reads prices from there. Runs never fetch it:
commands that estimate costs refresh the cache first when it is more than a day old, and keep
the old copy if the fetch fails, so runs work offline. Costs are estimates either way: the token
counts each provider reports, times these prices.

Names: our model names are Inspect's (``anthropic/claude-opus-5-5``,
``openrouter/z-ai/glm-5.3-flash``). OpenRouter's use dots in versions (``anthropic/claude-opus-5.5``).
A name matches when the two agree after dropping an ``openrouter/`` prefix and a ``:variant``
suffix, ignoring case and treating "." and "-" alike. Variants such as ``:batch`` and ``:free``
are never used.

Prices that change with prompt length (OpenRouter's ``overrides``, e.g. above 272k input
tokens) are not modelled; the base price is used, so the figures are in the right range rather
than exact. (Inspect itself applies Anthropic's dearer one-hour cache writes.)
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from inspect_ai.model import ModelCost

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
MAX_AGE = timedelta(days=1)
FETCH_TIMEOUT_SECONDS = 15
OFFLINE_ENV = "SWARMBENCH_PRICES_OFFLINE"
CACHE_ENV = "SWARMBENCH_PRICE_CACHE"


def cache_path() -> Path:
    """Where the price list is saved: $SWARMBENCH_PRICE_CACHE, else the user's cache folder."""
    if os.environ.get(CACHE_ENV):
        return Path(os.environ[CACHE_ENV])
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "swarmbench" / "openrouter-prices.json"


def canonical(name: str) -> str:
    """The form two model names are compared in."""
    name = name.strip().lower().removeprefix("openrouter/").split(":", 1)[0]
    return name.replace(".", "-")


# --- reading OpenRouter's list ----------------------------------------------------------------------


def _per_million(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number * 1_000_000, 6) if number >= 0 else None  # -1 means "varies" (routers)


def parse_models(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    """OpenRouter's response as {model id: dollars per million tokens}. Models without an input
    and an output price, routers and ``:variant`` entries are left out. A missing cache price is
    taken as the input price (caching is then simply not cheaper)."""
    out: dict[str, dict[str, float]] = {}
    for model in data.get("data") or []:
        mid = str(model.get("id") or "")
        pricing = model.get("pricing") or {}
        if not mid or ":" in mid:
            continue
        price_in, price_out = _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
        if price_in is None or price_out is None:
            continue
        out[mid] = {
            "input": price_in,
            "output": price_out,
            "input_cache_write": _per_million(pricing.get("input_cache_write")) or price_in,
            "input_cache_read": _per_million(pricing.get("input_cache_read")) or price_in,
        }
    return out


# --- the cache --------------------------------------------------------------------------------------


@dataclass
class PriceList:
    fetched: datetime | None = None
    models: dict[str, dict[str, float]] = field(default_factory=dict)
    """OpenRouter id -> dollars per million tokens."""
    by_canonical: dict[str, str] = field(default_factory=dict)

    def lookup(self, model: str) -> tuple[str, ModelCost] | None:
        """(OpenRouter's id, price) for one of our model names, or None."""
        mid = self.by_canonical.get(canonical(model))
        return (mid, ModelCost(**self.models[mid])) if mid else None

    @property
    def age(self) -> timedelta | None:
        return datetime.now(UTC) - self.fetched if self.fetched else None


_loaded: dict[str, tuple[float, PriceList]] = {}


def load(path: Path | None = None) -> PriceList:
    """The saved price list (empty if there is none or it can't be read). Read once per change."""
    file = path or cache_path()
    try:
        mtime = file.stat().st_mtime
    except OSError:
        return PriceList()
    cached = _loaded.get(str(file))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(file.read_text())
        models = {
            str(k): {f: float(v[f]) for f in ("input", "output", "input_cache_write", "input_cache_read")}
            for k, v in (data.get("models") or {}).items()
        }
        fetched = datetime.fromisoformat(data["fetched"]) if data.get("fetched") else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return PriceList()
    prices = PriceList(fetched, models, {canonical(k): k for k in sorted(models)})
    _loaded[str(file)] = (mtime, prices)
    return prices


def lookup(model: str) -> ModelCost | None:
    """A model's price from the saved OpenRouter list, or None."""
    found = load().lookup(model)
    return found[1] if found else None


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- refreshing -------------------------------------------------------------------------------------


@dataclass
class Refresh:
    status: str
    """"fresh" (recent enough, not fetched), "updated", "failed" or "offline"."""
    fetched: datetime | None = None
    changed: list[tuple[str, dict[str, float] | None, dict[str, float] | None]] = field(default_factory=list)
    """(model id, old price, new price) for every price that changed, was added or was removed."""
    error: str = ""
    count: int = 0


def fetch(url: str = OPENROUTER_MODELS_URL, timeout: float = FETCH_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "swarmbench"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def refresh(force: bool = False, fetcher=fetch, path: Path | None = None) -> Refresh:
    """Fetch OpenRouter's list if the saved one is older than MAX_AGE (or always, with
    ``force``). A failed fetch keeps the saved list. $SWARMBENCH_PRICES_OFFLINE turns fetching off."""
    file = path or cache_path()
    old = load(file)
    if os.environ.get(OFFLINE_ENV) and not force:
        return Refresh("offline", old.fetched, count=len(old.models))
    if not force and old.age is not None and old.age < MAX_AGE:
        return Refresh("fresh", old.fetched, count=len(old.models))
    try:
        models = parse_models(fetcher())
        if not models:
            raise ValueError("the list had no priced models")
    except Exception as exc:
        return Refresh(
            "failed", old.fetched, error=str(exc)[:200] or type(exc).__name__, count=len(old.models)
        )
    now = datetime.now(UTC)
    try:
        _write_atomic(
            file,
            json.dumps(
                {"fetched": now.isoformat(), "source": OPENROUTER_MODELS_URL, "models": models},
                indent=1,
                sort_keys=True,
            )
            + "\n",
        )
    except OSError as exc:  # e.g. a full disk: the saved list still works
        return Refresh("failed", old.fetched, error=f"couldn't save it: {exc}"[:200], count=len(old.models))
    changed = (
        [
            (m, old.models.get(m), models.get(m))
            for m in sorted(set(old.models) | set(models))
            if old.models.get(m) != models.get(m)
        ]
        if old.models
        else []
    )
    return Refresh("updated", now, changed, count=len(models))


def describe(r: Refresh) -> str:
    """One plain line about the price list, for commands that estimate costs."""
    when = r.fetched.astimezone().strftime("%Y-%m-%d") if r.fetched else None
    if r.status == "failed":
        kept = (
            f"; using the saved list from {when}"
            if when
            else "; no saved list, so prices come from prices.yaml or Inspect"
        )
        return f"Couldn't update model prices from OpenRouter ({r.error}){kept}."
    if r.status == "updated":
        return f"Updated model prices from OpenRouter ({r.count} models)."
    return ""
