import os
import time
from pathlib import Path
from typing import Union


def cleanup_expired_partials(storage_root: Union[str, Path], ttl_seconds: int) -> int:
    """Scan storage directory and remove expired .part and .part.meta files.

    Returns the number of cleaned up files.
    """
    if ttl_seconds <= 0:
        return 0

    now = time.time()
    cleaned_count = 0
    storage_path = Path(storage_root)

    if not storage_path.exists():
        return 0

    # Quét tất cả file .part và .part.meta trong tất cả các user storage
    for entry in storage_path.glob("**/*"):
        if entry.is_file() and (
            entry.name.endswith(".part") or entry.name.endswith(".part.meta")
        ):
            try:
                mtime = entry.stat().st_mtime
                if now - mtime > ttl_seconds:
                    entry.unlink(missing_ok=True)
                    cleaned_count += 1
            except OSError:
                pass

    return cleaned_count 