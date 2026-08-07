from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
from threading import Barrier, Event, Lock
from time import sleep

import pytest

from hcmus_socket.config import AppConfig, ServerConfig
from hcmus_socket.messages import FileUpload, make_file_upload_frame
from hcmus_socket.protocol import Frame, Opcode
from hcmus_socket.server.filename_locks import FilenameLockRegistry
from hcmus_socket.server.session import ServerSession, SessionState


def test_same_filename_is_exclusive_and_registry_cleans_itself() -> None:
    registry = FilenameLockRegistry()
    counter_guard = Lock()
    active = 0
    maximum_active = 0

    def work() -> None:
        nonlocal active, maximum_active
        with registry.hold("alice", "shared.bin"):
            with counter_guard:
                active += 1
                maximum_active = max(maximum_active, active)
            sleep(0.005)
            with counter_guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(lambda _index: work(), range(40)))

    assert maximum_active == 1
    assert registry.active_key_count == 0
    assert registry.snapshot() == ()


def test_different_namespaces_and_filenames_do_not_block_each_other() -> None:
    registry = FilenameLockRegistry()
    barrier = Barrier(3)

    def hold(namespace: str, filename: str) -> None:
        with registry.hold(namespace, filename):
            barrier.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(hold, "alice", "same.bin"),
            executor.submit(hold, "bob", "same.bin"),
            executor.submit(hold, "alice", "other.bin"),
        ]
        for future in futures:
            future.result(timeout=3)

    assert registry.active_key_count == 0


def test_exception_releases_filename_lock() -> None:
    registry = FilenameLockRegistry()

    with pytest.raises(RuntimeError):
        with registry.hold("alice", "data.bin"):
            raise RuntimeError("transfer failed")

    assert registry.active_key_count == 0
    with registry.hold("alice", "data.bin"):
        assert registry.snapshot() == (("alice", "data.bin"),)


def test_dispatcher_serializes_same_filename_without_transfer_changes(
    tmp_path: Path,
) -> None:
    locks = FilenameLockRegistry()
    counter_guard = Lock()
    first_entered = Event()
    allow_first_to_finish = Event()
    active = 0
    maximum_active = 0

    def upload_handler(_session: ServerSession, _frame: Frame) -> None:
        nonlocal active, maximum_active
        with counter_guard:
            active += 1
            maximum_active = max(maximum_active, active)
            is_first = not first_entered.is_set()
            if is_first:
                first_entered.set()
        if is_first:
            assert allow_first_to_finish.wait(timeout=2)
        with counter_guard:
            active -= 1

    config = AppConfig(server=ServerConfig(storage_directory=tmp_path))
    sockets = [socket.socketpair() for _ in range(2)]
    sessions = [
        ServerSession(
            server_socket,
            ("local", index),
            config,
            {Opcode.FILE_UPLOAD: upload_handler},
            filename_locks=locks,
        )
        for index, (server_socket, _client_socket) in enumerate(sockets)
    ]
    for session in sessions:
        session.state = SessionState.IDLE
    frame = make_file_upload_frame(FileUpload("shared.bin", 0))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(session._dispatch, frame) for session in sessions]
            assert first_entered.wait(timeout=2)
            sleep(0.02)
            assert maximum_active == 1
            allow_first_to_finish.set()
            for future in futures:
                future.result(timeout=2)
    finally:
        allow_first_to_finish.set()
        for session, (_server_socket, client_socket) in zip(sessions, sockets):
            session.close()
            client_socket.close()

    assert maximum_active == 1
    assert locks.active_key_count == 0
