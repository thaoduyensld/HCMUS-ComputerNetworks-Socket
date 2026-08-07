"""Helpers for resumable partial-transfer metadata and prefix hashing."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import mkstemp
from time import sleep
from typing import Any


METADATA_REPLACE_ATTEMPTS = 6
METADATA_RETRY_DELAY_SECONDS = 0.01


def get_part_paths(target_path: Path) -> tuple[Path, Path]:
    """Return the data and metadata paths for an incomplete upload."""

    part_path = target_path.with_name(f"{target_path.name}.part")
    meta_path = target_path.with_name(f"{target_path.name}.part.meta")
    return part_path, meta_path


def save_part_metadata(
    meta_path: Path,
    total_size: int,
    uploaded_bytes: int,
) -> None:
    """Atomically persist partial metadata, retrying transient Windows locks."""

    data = {
        "total_size": total_size,
        "uploaded_bytes": uploaded_bytes,
    }
    descriptor, temporary_name = mkstemp(
        dir=meta_path.parent,
        prefix=f".{meta_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, separators=(",", ":"))
        for attempt in range(METADATA_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary_path, meta_path)
                return
            except OSError:
                if attempt + 1 == METADATA_REPLACE_ATTEMPTS:
                    raise
                sleep(METADATA_RETRY_DELAY_SECONDS * (attempt + 1))
    finally:
        temporary_path.unlink(missing_ok=True)


def load_part_metadata(meta_path: Path) -> dict[str, Any] | None:
    """Return valid JSON metadata, or ``None`` when it cannot be loaded."""

    if not meta_path.exists():
        return None
    try:
        with meta_path.open("r", encoding="utf-8") as source:
            loaded = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def compute_prefix_hash(
    file_path: Path,
    length: int,
) -> tuple[Any, int]:
    """Hash at most *length* prefix bytes and return the hasher and byte count."""

    hasher = hashlib.sha256()
    bytes_read = 0
    if not file_path.exists():
        return hasher, 0

    with file_path.open("rb") as source:
        remaining = length
        while remaining > 0:
            chunk = source.read(min(remaining, 32 * 1024))
            if not chunk:
                break
            hasher.update(chunk)
            bytes_read += len(chunk)
            remaining -= len(chunk)
    return hasher, bytes_read
