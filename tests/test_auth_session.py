from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import socket
import struct

import pytest

from hcmus_socket.config import AppConfig, ServerConfig
from hcmus_socket.framing import (
    encode_preface,
    receive_frame,
    recv_exact,
    send_all,
    send_frame,
)
from hcmus_socket.messages import (
    FileUpload,
    LoginRequest,
    make_disconnect_frame,
    make_file_upload_frame,
    make_login_frame,
    parse_acknowledgement,
    parse_error,
)
from hcmus_socket.protocol import ErrorCode, Opcode
from hcmus_socket.server.identity import IdentityRegistry
from hcmus_socket.server.session import ServerSession, SessionState


def make_config(storage: Path) -> AppConfig:
    return AppConfig(server=ServerConfig(storage_directory=storage))


def start_session(
    executor: ThreadPoolExecutor,
    config: AppConfig,
    registry: IdentityRegistry,
    *,
    handlers: dict[Opcode, object] | None = None,
) -> tuple[ServerSession, socket.socket, Future[None]]:
    server_socket, client = socket.socketpair()
    client.settimeout(2)
    session = ServerSession(
        server_socket,
        ("local", 0),
        config,
        handlers=handlers,  # type: ignore[arg-type]
        identity_registry=registry,
    )
    return session, client, executor.submit(session.run)


def exchange_preface(client: socket.socket) -> None:
    send_all(client, encode_preface())
    assert recv_exact(client, 8) == encode_preface()


def login(client: socket.socket, username: str) -> int:
    exchange_preface(client)
    return retry_login(client, username)


def retry_login(client: socket.socket, username: str) -> int:
    send_frame(client, make_login_frame(LoginRequest(username)))
    response = receive_frame(client)
    assert response is not None
    acknowledgement = parse_acknowledgement(response)
    assert acknowledgement.acknowledged_opcode is Opcode.LOGIN
    assert acknowledgement.next_offset == 0
    return response.user_id


def disconnect(client: socket.socket, user_id: int) -> None:
    send_frame(client, make_disconnect_frame(user_id=user_id))
    response = receive_frame(client)
    assert response is not None
    assert parse_acknowledgement(response).acknowledged_opcode is Opcode.DISCONNECT


def test_valid_login_assigns_identity_creates_namespace_and_enters_idle(
    tmp_path: Path,
) -> None:
    registry = IdentityRegistry()
    with ThreadPoolExecutor(max_workers=1) as executor:
        session, client, future = start_session(
            executor, make_config(tmp_path), registry
        )
        user_id = login(client, "Alice")

        assert user_id != 0
        assert session.state is SessionState.IDLE
        assert session.authenticated
        assert session.username == "Alice"
        assert session.user_id == user_id
        assert (tmp_path / "Alice").is_dir()
        assert registry.active_count == 1

        disconnect(client, user_id)
        future.result(timeout=2)
        assert registry.active_count == 0
        client.close()


def test_different_active_usernames_receive_different_ids(tmp_path: Path) -> None:
    registry = IdentityRegistry()
    with ThreadPoolExecutor(max_workers=2) as executor:
        _first, first_client, first_future = start_session(
            executor, make_config(tmp_path), registry
        )
        _second, second_client, second_future = start_session(
            executor, make_config(tmp_path), registry
        )
        first_id = login(first_client, "alice")
        second_id = login(second_client, "bob")

        assert first_id != second_id
        assert registry.active_count == 2

        disconnect(first_client, first_id)
        disconnect(second_client, second_id)
        first_future.result(timeout=2)
        second_future.result(timeout=2)
        assert registry.active_count == 0
        first_client.close()
        second_client.close()


def test_duplicate_username_is_rejected_then_reusable_after_release(
    tmp_path: Path,
) -> None:
    registry = IdentityRegistry()
    with ThreadPoolExecutor(max_workers=2) as executor:
        _first, first_client, first_future = start_session(
            executor, make_config(tmp_path), registry
        )
        _second, second_client, second_future = start_session(
            executor, make_config(tmp_path), registry
        )
        first_id = login(first_client, "alice")
        exchange_preface(second_client)
        send_frame(second_client, make_login_frame(LoginRequest("alice")))
        rejection = receive_frame(second_client)
        assert rejection is not None
        error = parse_error(rejection)
        assert rejection.user_id == 0
        assert error.error_code is ErrorCode.USERNAME_IN_USE

        disconnect(first_client, first_id)
        first_future.result(timeout=2)
        reused_id = retry_login(second_client, "alice")
        assert reused_id == first_id

        disconnect(second_client, reused_id)
        second_future.result(timeout=2)
        assert registry.active_count == 0
        first_client.close()
        second_client.close()


def test_identity_is_released_when_socket_drops(tmp_path: Path) -> None:
    registry = IdentityRegistry()
    with ThreadPoolExecutor(max_workers=1) as executor:
        _session, client, future = start_session(
            executor, make_config(tmp_path), registry
        )
        login(client, "alice")
        assert registry.active_count == 1

        client.close()
        future.result(timeout=2)
        assert registry.active_count == 0


def test_identity_is_released_after_framing_error(tmp_path: Path) -> None:
    registry = IdentityRegistry()
    with ThreadPoolExecutor(max_workers=1) as executor:
        _session, client, future = start_session(
            executor, make_config(tmp_path), registry
        )
        user_id = login(client, "alice")
        send_all(client, struct.pack("!IHH", 8, Opcode.FILE_LIST, user_id) + b"xx")
        client.close()

        with pytest.raises(Exception):
            future.result(timeout=2)
        assert registry.active_count == 0


def test_identity_is_released_when_handler_raises(tmp_path: Path) -> None:
    registry = IdentityRegistry()

    def fail_handler(_session: ServerSession, _frame: object) -> None:
        raise RuntimeError("handler failed")

    with ThreadPoolExecutor(max_workers=1) as executor:
        _session, client, future = start_session(
            executor,
            make_config(tmp_path),
            registry,
            handlers={Opcode.FILE_UPLOAD: fail_handler},
        )
        user_id = login(client, "alice")
        send_frame(
            client,
            make_file_upload_frame(FileUpload("x.bin", 0), user_id=user_id),
        )

        with pytest.raises(RuntimeError, match="handler failed"):
            future.result(timeout=2)
        assert registry.active_count == 0
        client.close()
