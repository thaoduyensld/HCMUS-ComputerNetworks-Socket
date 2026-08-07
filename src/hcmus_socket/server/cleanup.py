"""Cleanup policy for expired resumable-upload artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from time import time


def cleanup_expired_partials(
    storage_root: str | Path,
    ttl_seconds: int,
    *,
    now: float | None = None,
) -> int:
    """Remove expired partial pairs below *storage_root*.

    A zero TTL disables automatic cleanup. Artifacts are grouped as
    ``<name>.part`` and ``<name>.part.meta`` so a fresh member protects the
    whole pair and an expired pair is removed together. Symlinks are ignored.
    The return value counts files actually removed.
    """

    if ttl_seconds < 0:
        raise ValueError("ttl_seconds must not be negative")
    if ttl_seconds == 0:
        return 0

    root = Path(storage_root)
    if not root.is_dir() or root.is_symlink():
        return 0

    pairs: dict[Path, set[Path]] = {}
    try:
        walker = os.walk(root, followlinks=False)
        for directory, _subdirectories, filenames in walker:
            parent = Path(directory)
            for filename in filenames:
                if filename.endswith(".part.meta"):
                    part = parent / filename.removesuffix(".meta")
                elif filename.endswith(".part"):
                    part = parent / filename
                else:
                    continue
                candidate = parent / filename
                if candidate.is_symlink():
                    continue
                pairs.setdefault(part, set()).add(candidate)
    except OSError:
        return 0

    current_time = time() if now is None else now
    cleaned = 0
    for part_path, discovered in pairs.items():
        meta_path = part_path.with_name(part_path.name + ".meta")
        members = discovered | {part_path, meta_path}
        existing: list[tuple[Path, float]] = []
        for member in members:
            try:
                if member.is_file() and not member.is_symlink():
                    existing.append((member, member.stat().st_mtime))
            except OSError:
                pass
        if not existing:
            continue
        if current_time - max(mtime for _path, mtime in existing) <= ttl_seconds:
            continue
        for member, _mtime in existing:
            try:
                member.unlink()
            except OSError:
                continue
            cleaned += 1
    return cleaned


def cleanup_expired_partial_pair(
    part_path: Path,
    meta_path: Path,
    ttl_seconds: int,
    *,
    now: float | None = None,
) -> bool:
    """Remove one expired pair while its filename lock is held."""

    if ttl_seconds < 0:
        raise ValueError("ttl_seconds must not be negative")
    if ttl_seconds == 0:
        return False
    existing: list[tuple[Path, float]] = []
    for path in (part_path, meta_path):
        try:
            if path.is_file() and not path.is_symlink():
                existing.append((path, path.stat().st_mtime))
        except OSError:
            pass
    if not existing:
        return False
    current_time = time() if now is None else now
    if current_time - max(mtime for _path, mtime in existing) <= ttl_seconds:
        return False
    for path, _mtime in existing:
        try:
            path.unlink()
        except OSError:
            pass
    return True
