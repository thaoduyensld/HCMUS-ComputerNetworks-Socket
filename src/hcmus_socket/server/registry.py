"""Thread-safe active session, username, and wire user-ID registry."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from threading import RLock


MIN_USER_ID = 1
MAX_USER_ID = (1 << 16) - 1


class RegistryError(RuntimeError):
    """Base class for registry policy and capacity failures."""


class UnknownSessionError(RegistryError):
    """Raised when an operation references a session that is not active."""


class SessionAlreadyAuthenticatedError(RegistryError):
    """Raised when one session attempts to claim a second username."""


class UsernameInUseError(RegistryError):
    """Raised when an active session already owns a username."""


class UserIdCapacityError(RegistryError):
    """Raised when no wire USER_ID remains available."""


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: int
    peer_address: object
    username: str | None = None
    user_id: int | None = None


class ActiveSessionRegistry:
    """Atomically track sessions and unique authenticated identities."""

    def __init__(self, *, maximum_user_id: int = MAX_USER_ID) -> None:
        if not MIN_USER_ID <= maximum_user_id <= MAX_USER_ID:
            raise ValueError(
                f"maximum_user_id must be from {MIN_USER_ID} to {MAX_USER_ID}"
            )
        self._maximum_user_id = maximum_user_id
        self._lock = RLock()
        self._sessions: dict[int, SessionSnapshot] = {}
        self._username_owners: dict[str, int] = {}
        self._next_session_id = 1
        self._next_user_id = MIN_USER_ID
        self._free_user_ids: list[int] = []

    def register_session(self, peer_address: object) -> SessionSnapshot:
        """Create and return one active unauthenticated session record."""

        with self._lock:
            session_id = self._next_session_id
            self._next_session_id += 1
            record = SessionSnapshot(session_id, peer_address)
            self._sessions[session_id] = record
            return record

    def claim_username(self, session_id: int, username: str) -> SessionSnapshot:
        """Atomically bind a unique username and nonzero USER_ID to a session."""

        if not isinstance(username, str) or not username:
            raise ValueError("username must be non-empty text")
        with self._lock:
            current = self._require_session(session_id)
            if current.username is not None:
                if current.username == username:
                    return current
                raise SessionAlreadyAuthenticatedError(
                    f"session {session_id} already owns username {current.username!r}"
                )
            owner = self._username_owners.get(username)
            if owner is not None:
                raise UsernameInUseError(
                    f"username {username!r} is already owned by session {owner}"
                )
            user_id = self._allocate_user_id()
            claimed = SessionSnapshot(
                current.session_id,
                current.peer_address,
                username,
                user_id,
            )
            self._sessions[session_id] = claimed
            self._username_owners[username] = session_id
            return claimed

    def release_session(self, session_id: int) -> SessionSnapshot | None:
        """Remove a session and make its username and USER_ID available again."""

        with self._lock:
            record = self._sessions.pop(session_id, None)
            if record is None:
                return None
            if record.username is not None:
                self._username_owners.pop(record.username, None)
            if record.user_id is not None:
                heapq.heappush(self._free_user_ids, record.user_id)
            return record

    def get_session(self, session_id: int) -> SessionSnapshot:
        with self._lock:
            return self._require_session(session_id)

    def owner_of(self, username: str) -> SessionSnapshot | None:
        with self._lock:
            session_id = self._username_owners.get(username)
            return self._sessions.get(session_id) if session_id is not None else None

    def snapshot(self) -> tuple[SessionSnapshot, ...]:
        with self._lock:
            return tuple(self._sessions.values())

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    @property
    def authenticated_count(self) -> int:
        with self._lock:
            return len(self._username_owners)

    def _require_session(self, session_id: int) -> SessionSnapshot:
        try:
            return self._sessions[session_id]
        except KeyError as error:
            raise UnknownSessionError(f"session {session_id} is not active") from error

    def _allocate_user_id(self) -> int:
        if self._free_user_ids:
            return heapq.heappop(self._free_user_ids)
        if self._next_user_id > self._maximum_user_id:
            raise UserIdCapacityError("no USER_ID remains available")
        user_id = self._next_user_id
        self._next_user_id += 1
        return user_id
