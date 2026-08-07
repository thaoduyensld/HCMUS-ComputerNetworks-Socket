from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from hcmus_socket.server.registry import (
    ActiveSessionRegistry,
    SessionAlreadyAuthenticatedError,
    UserIdCapacityError,
    UsernameInUseError,
)


def test_claim_and_release_reuses_username_and_lowest_user_id() -> None:
    registry = ActiveSessionRegistry()
    first = registry.register_session(("127.0.0.1", 1001))
    claimed = registry.claim_username(first.session_id, "ngoc")

    assert claimed.user_id == 1
    assert registry.owner_of("ngoc") == claimed
    assert registry.authenticated_count == 1
    assert registry.release_session(first.session_id) == claimed
    assert registry.active_count == 0
    assert registry.owner_of("ngoc") is None

    second = registry.register_session(("127.0.0.1", 1002))
    reused = registry.claim_username(second.session_id, "ngoc")
    assert reused.user_id == 1


def test_claim_is_idempotent_but_cannot_change_username() -> None:
    registry = ActiveSessionRegistry()
    session = registry.register_session("peer")
    claimed = registry.claim_username(session.session_id, "alice")

    assert registry.claim_username(session.session_id, "alice") == claimed
    with pytest.raises(SessionAlreadyAuthenticatedError):
        registry.claim_username(session.session_id, "bob")


def test_same_username_can_only_be_claimed_once_under_race() -> None:
    registry = ActiveSessionRegistry()
    sessions = [registry.register_session(index) for index in range(20)]
    barrier = Barrier(len(sessions))

    def claim(session_id: int) -> int | None:
        barrier.wait()
        try:
            return registry.claim_username(session_id, "shared").session_id
        except UsernameInUseError:
            return None

    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        winners = list(executor.map(lambda item: claim(item.session_id), sessions))

    assert sum(winner is not None for winner in winners) == 1
    assert registry.authenticated_count == 1


def test_parallel_unique_claims_receive_distinct_user_ids() -> None:
    registry = ActiveSessionRegistry()
    sessions = [registry.register_session(index) for index in range(100)]

    with ThreadPoolExecutor(max_workers=20) as executor:
        claimed = list(
            executor.map(
                lambda item: registry.claim_username(
                    item.session_id,
                    f"user-{item.session_id}",
                ),
                sessions,
            )
        )

    assert len({item.user_id for item in claimed}) == 100
    assert registry.active_count == 100
    assert registry.authenticated_count == 100


def test_user_id_capacity_is_enforced_without_partial_claim() -> None:
    registry = ActiveSessionRegistry(maximum_user_id=2)
    sessions = [registry.register_session(index) for index in range(3)]
    registry.claim_username(sessions[0].session_id, "one")
    registry.claim_username(sessions[1].session_id, "two")

    with pytest.raises(UserIdCapacityError):
        registry.claim_username(sessions[2].session_id, "three")

    assert registry.get_session(sessions[2].session_id).username is None
    assert registry.owner_of("three") is None
