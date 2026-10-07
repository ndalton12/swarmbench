"""Reading, staging and writing scenario folders safely.

Everything the model writes goes through ``safe_path`` first, so a reply can
never point outside the scenario folder. Output folders are created with
``copytree`` from a validated staging copy and never overwrite anything.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath

MAX_FILES = 120
MAX_FILE_BYTES = 300_000
MAX_TOTAL_BYTES = 3_000_000

_PART = re.compile(r"[A-Za-z0-9_@+.,=-][A-Za-z0-9_@+. ,=-]*")
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_SKIP_FILES = {".DS_Store", ".rm-protect"}


class UnsafePath(ValueError):
    pass


def safe_path(path: str) -> str:
    """Normalise a model-supplied relative path, or raise UnsafePath."""
    if not path or "\\" in path or "\x00" in path:
        raise UnsafePath(f"{path!r}: use a plain relative path with forward slashes")
    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise UnsafePath(f"{path!r}: must be relative to the scenario folder")
    parts = pure.parts
    if not parts or len(parts) > 10:
        raise UnsafePath(f"{path!r}: empty or too deep")
    for part in parts:
        if part in (".", "..") or not _PART.fullmatch(part) or len(part) > 100:
            raise UnsafePath(f"{path!r}: unsupported path component {part!r}")
        if part in _SKIP_DIRS:
            raise UnsafePath(f"{path!r}: {part} folders can't be written as files (use history.yaml for git)")
    return "/".join(parts)


def read_folder(root: Path) -> tuple[dict[str, str], dict[str, bytes]]:
    """All files under ``root`` as (text files, binary files), keyed by relative path."""
    texts: dict[str, str] = {}
    binaries: dict[str, bytes] = {}
    for file in sorted(root.rglob("*")):
        rel = file.relative_to(root)
        if any(p in _SKIP_DIRS for p in rel.parts) or file.name in _SKIP_FILES:
            continue
        if file.is_symlink() or not file.is_file():
            continue
        data = file.read_bytes()
        try:
            texts[rel.as_posix()] = data.decode("utf-8")
        except UnicodeDecodeError:
            binaries[rel.as_posix()] = data
    return texts, binaries


def check_sizes(files: dict[str, str]) -> list[str]:
    errors = []
    if len(files) > MAX_FILES:
        errors.append(f"too many files ({len(files)}); keep it under {MAX_FILES}")
    total = 0
    for path, text in files.items():
        size = len(text.encode())
        total += size
        if size > MAX_FILE_BYTES:
            errors.append(f"{path} is {size} bytes; keep each file under {MAX_FILE_BYTES}")
    if total > MAX_TOTAL_BYTES:
        errors.append(f"files total {total} bytes; keep the scenario under {MAX_TOTAL_BYTES}")
    return errors


def write_files(root: Path, texts: dict[str, str], binaries: dict[str, bytes] | None = None) -> None:
    """Write files under ``root`` (which must be a fresh staging folder)."""
    for rel, text in texts.items():
        target = root / safe_path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    for rel, data in (binaries or {}).items():
        target = root / safe_path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def publish(staging: Path, target: Path) -> Path:
    """Copy a validated staging folder to ``target``. Fails if ``target`` exists."""
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"{target} already exists; the designer never overwrites")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staging, target, symlinks=False, dirs_exist_ok=False)
    return target


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len].rstrip("_") or "scenario"


def free_name(parent: Path, base: str) -> Path:
    """``parent/base``, or ``parent/base_2``, ``base_3``... whichever is free first."""
    candidate = parent / base
    n = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = parent / f"{base}_{n}"
        n += 1
    return candidate


def next_version(scenario_dir: Path) -> tuple[Path, int]:
    """The next free ``<scenario>_vN`` folder beside ``scenario_dir`` (N starts at 2)."""
    base = re.sub(r"_v\d+$", "", scenario_dir.name)
    n = 2
    while True:
        candidate = scenario_dir.parent / f"{base}_v{n}"
        if not (candidate.exists() or candidate.is_symlink()):
            return candidate, n
        n += 1
