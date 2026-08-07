from __future__ import annotations

from collections import deque
import socket

import pytest

from hcmus_socket.client.session import AuthenticationError, ClientSession, SessionError
from hcmus_socket.config import AppConfig, ClientConfig
from hcmus_socket.framing import encode_preface, serialize_frame
from hcmus_socket.messages import (
    Acknowledgement,
    ErrorMessage,
    LoginRequest,
    make_acknowledgement_frame,
    make_error_frame,
    make_file_list_frame,
    make_login_frame,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode, ProtocolError


class ScriptedSocket:
    def __init__(self, incoming: bytes) -> None:
        self.incoming = deque([bytearray(incoming)])
        self.sent = bytearray()
        self.closed = False
        self.shutdown_modes: list[int] = []
        self.timeout_values: list[float | None] = []

    def send(self, data: memoryview) -> int:
        self.sent.extend(data)
        return len(data)

    def recv(self, size: int) -> bytes:
        if not self.incoming:
            return b""
        data = self.incoming[0]
        result = bytes(data[:size])
        del data[:size]
        if not data:
            self.incoming.popleft()
        return result

    def settimeout(self, value: float | None) -> None:
        self.timeout_values.append(value)

    def close(self) -> None:
        self.closed = True

    def shutdown(self, mode: int) -> None:
        self.shutdown_modes.append(mode)


def login_ack(user_id: int = 7) -> bytes:
    return serialize_frame(
        make_acknowledgement_frame(
            Acknowledgement(Opcode.LOGIN, 0),
            user_id=user_id,
        )
    )


def make_session(sock: ScriptedSocket, username: str = "alice") -> ClientSession:
    return ClientSession(
        AppConfig(),
        socket_factory=lambda *_args, **_kwargs: sock,  # type: ignore[arg-type]
        username=username,
    )


def test_connect_logs_in_and_disconnects_with_assigned_user_id() -> None:
    disconnect_ack = serialize_frame(
        make_acknowledgement_frame(
            Acknowledgement(Opcode.DISCONNECT, 0),
            user_id=7,
        )
    )
    sock = ScriptedSocket(encode_preface() + login_ack() + disconnect_ack)
    calls: list[tuple[tuple[str, int], float]] = []

    def factory(address: tuple[str, int], *, timeout: float) -> socket.socket:
        calls.append((address, timeout))
        return sock  # type: ignore[return-value]

    config = AppConfig(client=ClientConfig("192.0.2.10", 9000, 2500))
    session = ClientSession(config, socket_factory=factory, username="alice")
    session.connect()

    assert calls == [(('192.0.2.10', 9000), 2.5)]
    assert bytes(sock.sent).startswith(encode_preface())
    assert serialize_frame(make_login_frame(LoginRequest("alice"))) in bytes(sock.sent)
    assert sock.timeout_values == [None]
    assert session.authenticated
    assert session.username == "alice"
    assert session.user_id == 7

    session.disconnect()

    assert not session.connected
    assert not session.authenticated
    assert session.user_id == 0
    assert sock.closed


def test_connect_closes_socket_when_server_omits_preface() -> None:
    sock = ScriptedSocket(b"")
    session = make_session(sock)

    with pytest.raises(SessionError):
        session.connect()

    assert sock.closed
    assert not session.connected


def test_connect_requires_username_before_opening_socket() -> None:
    called = False

    def factory(*_args: object, **_kwargs: object) -> socket.socket:
        nonlocal called
        called = True
        raise AssertionError("socket factory must not be called")

    session = ClientSession(AppConfig(), socket_factory=factory)

    with pytest.raises(SessionError, match="username"):
        session.connect()

    assert not called


def test_double_connect_is_rejected() -> None:
    sock = ScriptedSocket(encode_preface() + login_ack())
    session = make_session(sock)
    session.connect()

    with pytest.raises(SessionError):
        session.connect()

    session.close(abort=True)

    assert sock.shutdown_modes == [socket.SHUT_RDWR]


def test_disconnect_ack_requires_zero_next_offset() -> None:
    invalid_ack = serialize_frame(
        make_acknowledgement_frame(
            Acknowledgement(Opcode.DISCONNECT, 1),
            user_id=7,
        )
    )
    sock = ScriptedSocket(encode_preface() + login_ack() + invalid_ack)
    session = make_session(sock)
    session.connect()

    with pytest.raises(SessionError, match="next_offset"):
        session.disconnect()

    assert sock.closed
    assert not session.connected


def test_login_ack_assigns_session_user_id() -> None:
    sock = ScriptedSocket(encode_preface() + login_ack())
    session = make_session(sock)

    session.connect()

    assert session.user_id == 7
    assert session.authenticated
    session.close(abort=True)


def test_client_rejects_frame_for_different_session_user_id() -> None:
    incoming = serialize_frame(Frame(Opcode.FILE_LIST_RESP, b"\x00\x00\x00\x00", 8))
    sock = ScriptedSocket(encode_preface() + login_ack() + incoming)
    session = make_session(sock)
    session.connect()

    with pytest.raises(SessionError, match="USER_ID"):
        session.receive()

    assert sock.closed


@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.SERVER_BUSY,
        ErrorCode.INVALID_USERNAME,
        ErrorCode.USERNAME_IN_USE,
    ],
)
def test_client_reports_login_rejection_and_closes(code: ErrorCode) -> None:
    rejection = serialize_frame(
        make_error_frame(ErrorMessage(Opcode.LOGIN, code, "login rejected"))
    )
    sock = ScriptedSocket(encode_preface() + rejection)
    session = make_session(sock)

    with pytest.raises(AuthenticationError, match=code.name) as raised:
        session.connect()

    assert raised.value.code is code
    assert sock.closed
    assert not session.connected
    assert not session.authenticated


def test_authenticated_client_rejects_outgoing_wrong_user_id() -> None:
    sock = ScriptedSocket(encode_preface() + login_ack())
    session = make_session(sock)
    session.connect()

    with pytest.raises(ProtocolError):
        session.send(make_file_list_frame(user_id=8))

    session.close(abort=True)
