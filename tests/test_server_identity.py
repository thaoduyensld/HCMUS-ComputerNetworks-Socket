from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from hcmus_socket.server.identity import (
    IdentityCapacityError,
    IdentityRegistry,
    UsernameInUseError,
)


def test_registry_assigns_unique_ids_and_reuses_released_identity() -> None:
    registry = IdentityRegistry()

    alice = registry.register("alice")
    bob = registry.register("bob")

    assert alice.user_id != bob.user_id
    assert registry.active_count == 2
    registry.release(alice)
    replacement = registry.register("alice")
    assert replacement.user_id == alice.user_id
    assert registry.active_count == 2


def test_registry_rejects_active_duplicate_username() -> None:
    registry = IdentityRegistry()
    registry.register("alice")

    with pytest.raises(UsernameInUseError):
        registry.register("alice")


def test_registry_is_thread_safe_for_duplicate_login() -> None:
    registry = IdentityRegistry()

    def register() -> int | None:
        try:
            return registry.register("alice").user_id
        except UsernameInUseError:
            return None

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _index: register(), range(64)))

    assert sum(result is not None for result in results) == 1
    assert registry.active_count == 1


def test_registry_reports_user_id_exhaustion() -> None:
    registry = IdentityRegistry(max_user_id=2)
    registry.register("alice")
    registry.register("bob")

    with pytest.raises(IdentityCapacityError):
        registry.register("charlie")
