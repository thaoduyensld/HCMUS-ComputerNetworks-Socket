from __future__ import annotations

from collections import deque
import socket

import pytest

from hcmus_socket.client.session import ClientSession, SessionError
from hcmus_socket.config import AppConfig, ClientConfig
from hcmus_socket.framing import encode_preface, serialize_frame
from hcmus_socket.messages import (
    Acknowledgement,
    LoginRequest,
    make_acknowledgement_frame,
    make_login_frame,
)
from hcmus_socket.protocol import Frame, Opcode


class ScriptedSocket:
    def __init__(self, incoming: bytes) -> None:
        self.incoming = deque([bytearray(incoming)])
        self.sent = bytearray()
        self.closed = False
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


def test_connect_and_disconnect_complete_protocol_handshakes() -> None:
    acknowledgement = serialize_frame(
        make_acknowledgement_frame(Acknowledgement(Opcode.DISCONNECT, 0))
    )
    sock = ScriptedSocket(encode_preface() + acknowledgement)
    calls: list[tuple[tuple[str, int], float]] = []

    def factory(address: tuple[str, int], *, timeout: float) -> socket.socket:
        calls.append((address, timeout))
        return sock  # type: ignore[return-value]

    config = AppConfig(client=ClientConfig("192.0.2.10", 9000, 2500))
    session = ClientSession(config, socket_factory=factory)
    session.connect()

    assert session.connected
    assert calls == [(('192.0.2.10', 9000), 2.5)]
    assert bytes(sock.sent) == encode_preface()
    assert sock.timeout_values == [None]

    session.disconnect()

    assert not session.connected
    assert sock.closed
    assert bytes(sock.sent).startswith(encode_preface())
    assert len(sock.sent) > len(encode_preface())


def test_connect_closes_socket_when_server_omits_preface() -> None:
    sock = ScriptedSocket(b"")
    session = ClientSession(
        AppConfig(),
        socket_factory=lambda *_args, **_kwargs: sock,  # type: ignore[arg-type]
    )

    with pytest.raises(SessionError):
        session.connect()

    assert sock.closed
    assert not session.connected


def test_double_connect_is_rejected() -> None:
    sock = ScriptedSocket(encode_preface())
    session = ClientSession(
        AppConfig(),
        socket_factory=lambda *_args, **_kwargs: sock,  # type: ignore[arg-type]
    )
    session.connect()

    with pytest.raises(SessionError):
        session.connect()

    session.close(abort=True)


def test_disconnect_ack_requires_zero_next_offset() -> None:
    acknowledgement = serialize_frame(
        make_acknowledgement_frame(Acknowledgement(Opcode.DISCONNECT, 1))
    )
    sock = ScriptedSocket(encode_preface() + acknowledgement)
    session = ClientSession(
        AppConfig(),
        socket_factory=lambda *_args, **_kwargs: sock,  # type: ignore[arg-type]
    )
    session.connect()

    with pytest.raises(SessionError, match="next_offset"):
        session.disconnect()

    assert sock.closed
    assert not session.connected


def test_login_ack_assigns_session_user_id() -> None:
    acknowledgement = serialize_frame(
        make_acknowledgement_frame(
            Acknowledgement(Opcode.LOGIN, 0),
            user_id=7,
        )
    )
    sock = ScriptedSocket(encode_preface() + acknowledgement)
    session = ClientSession(
        AppConfig(),
        socket_factory=lambda *_args, **_kwargs: sock,  # type: ignore[arg-type]
    )
    session.connect()
    session.send(make_login_frame(LoginRequest("alice")))

    response = session.receive()

    assert response.user_id == 7
    assert session.user_id == 7
    session.close(abort=True)


def test_client_rejects_frame_for_different_session_user_id() -> None:
    incoming = serialize_frame(Frame(Opcode.FILE_LIST_RESP, b"\x00\x00\x00\x00", 8))
    sock = ScriptedSocket(encode_preface() + incoming)
    session = ClientSession(
        AppConfig(),
        socket_factory=lambda *_args, **_kwargs: sock,  # type: ignore[arg-type]
    )
    session.connect()
    session.user_id = 7

    with pytest.raises(SessionError, match="USER_ID"):
        session.receive()

    assert sock.closed
