"""Thread-safe registry for active authenticated identities."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from threading import Lock

from ..protocol import MAX_USER_ID, MIN_USER_ID


@dataclass(frozen=True, slots=True)
class Identity:
    username: str
    user_id: int


class IdentityRegistryError(Exception):
    """Base class for expected identity registration failures."""


class UsernameInUseError(IdentityRegistryError):
    """Raised when an active session already owns a username."""


class IdentityCapacityError(IdentityRegistryError):
    """Raised when no protocol user ID remains available."""


class IdentityRegistry:
    """Allocate unique session IDs and enforce unique active usernames."""

    def __init__(self, *, max_user_id: int = MAX_USER_ID) -> None:
        if type(max_user_id) is not int or not MIN_USER_ID <= max_user_id <= MAX_USER_ID:
            raise ValueError(
                f"max_user_id must be from {MIN_USER_ID} to {MAX_USER_ID}"
            )
        self._max_user_id = max_user_id
        self._lock = Lock()
        self._by_username: dict[str, Identity] = {}
        self._by_user_id: dict[int, Identity] = {}
        self._released_user_ids: list[int] = []
        self._next_user_id = MIN_USER_ID

    def register(self, username: str) -> Identity:
        """Atomically reserve *username* and return a unique identity."""

        with self._lock:
            if username in self._by_username:
                raise UsernameInUseError(f"username {username!r} is already active")
            user_id = self._allocate_user_id_locked()
            identity = Identity(username, user_id)
            self._by_username[username] = identity
            self._by_user_id[user_id] = identity
            return identity

    def release(self, identity: Identity) -> None:
        """Release *identity* if it is still the active matching reservation."""

        with self._lock:
            active = self._by_user_id.get(identity.user_id)
            if active != identity:
                return
            self._by_user_id.pop(identity.user_id, None)
            self._by_username.pop(identity.username, None)
            heapq.heappush(self._released_user_ids, identity.user_id)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._by_user_id)

    def is_username_active(self, username: str) -> bool:
        with self._lock:
            return username in self._by_username

    def _allocate_user_id_locked(self) -> int:
        if self._released_user_ids:
            return heapq.heappop(self._released_user_ids)
        if self._next_user_id > self._max_user_id:
            raise IdentityCapacityError("no user ID is available")
        user_id = self._next_user_id
        self._next_user_id += 1
        return user_id
