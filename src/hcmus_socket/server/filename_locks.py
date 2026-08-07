"""Reference-counted filename locks shared by concurrent server sessions."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Iterator


FilenameKey = tuple[str, str]


@dataclass(slots=True)
class _LockEntry:
    lock: Lock = field(default_factory=Lock)
    references: int = 0


class FilenameLockRegistry:
    """Provide one exclusive lock for each namespace and filename pair."""

    def __init__(self) -> None:
        self._guard = Lock()
        self._entries: dict[FilenameKey, _LockEntry] = {}

    @contextmanager
    def hold(self, namespace: str, filename: str) -> Iterator[None]:
        """Hold an exclusive filename lock and remove it after the last user."""

        key = _validate_key(namespace, filename)
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = _LockEntry()
                self._entries[key] = entry
            entry.references += 1

        acquired = False
        try:
            entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            with self._guard:
                entry.references -= 1
                if entry.references == 0:
                    self._entries.pop(key, None)

    def snapshot(self) -> tuple[FilenameKey, ...]:
        """Return immutable keys currently held or awaited by a session."""

        with self._guard:
            return tuple(self._entries)

    @property
    def active_key_count(self) -> int:
        with self._guard:
            return len(self._entries)


def _validate_key(namespace: str, filename: str) -> FilenameKey:
    if not isinstance(namespace, str):
        raise ValueError("namespace must be text")
    if not isinstance(filename, str) or not filename:
        raise ValueError("filename must be non-empty text")
    return namespace, filename
