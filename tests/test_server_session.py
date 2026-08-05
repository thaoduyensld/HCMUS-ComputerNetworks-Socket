from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import socket
import struct

import pytest

from hcmus_socket.config import AppConfig, NetworkConfig, ServerConfig
from hcmus_socket.framing import (
    encode_preface,
    receive_frame,
    recv_exact,
    send_all,
    send_frame,
)
from hcmus_socket.messages import (
    FileUpload,
    make_disconnect_frame,
    make_file_list_frame,
    make_file_upload_frame,
    parse_acknowledgement,
    parse_error,
    parse_file_list_response,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode, ProtocolError
from hcmus_socket.server.app import create_listener, serve_forever
from hcmus_socket.server.session import ServerSession, SessionState


def make_config(storage: Path, max_payload_bytes: int = 1024 * 1024) -> AppConfig:
    return AppConfig(
        server=ServerConfig(
            bind_address="127.0.0.1",
            port=4567,
            storage_directory=storage,
        ),
        network=NetworkConfig(max_payload_bytes=max_payload_bytes),
    )


def start_session(
    executor: ThreadPoolExecutor,
    config: AppConfig,
) -> tuple[socket.socket, Future[None]]:
    server_socket, client_socket = socket.socketpair()
    client_socket.settimeout(2)
    session = ServerSession(server_socket, ("local", 0), config)
    return client_socket, executor.submit(session.run)


def handshake(client: socket.socket) -> None:
    send_all(client, encode_preface())
    assert recv_exact(client, 8) == encode_preface()


def test_server_handshake_echoes_exact_preface_and_enters_idle(tmp_path: Path) -> None:
    server_socket, client_socket = socket.socketpair()
    session = ServerSession(server_socket, ("local", 0), make_config(tmp_path))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(session.perform_handshake)
        handshake(client_socket)
        future.result(timeout=2)
    assert session.state is SessionState.IDLE
    client_socket.close()
    session.close()


@pytest.mark.parametrize(
    "preface",
    [
        struct.pack("!IHH", 0, 1, 0),
        struct.pack("!IHH", 0x48434D55, 2, 0),
        struct.pack("!IHH", 0x48434D55, 1, 1),
    ],
)
def test_invalid_preface_closes_session(tmp_path: Path, preface: bytes) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        send_all(client, preface)
        with pytest.raises(ProtocolError) as raised:
            future.result(timeout=2)
        assert raised.value.code is ErrorCode.INVALID_FRAME
        assert client.recv(1) == b""
        client.close()


@pytest.mark.parametrize("preface", [b"", encode_preface()[:4]])
def test_peer_close_before_or_mid_preface_is_fatal(
    tmp_path: Path,
    preface: bytes,
) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        if preface:
            send_all(client, preface)
        client.close()
        with pytest.raises(ProtocolError) as raised:
            future.result(timeout=2)
        assert raised.value.code is ErrorCode.INVALID_FRAME


def test_split_preface_is_accepted(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        preface = encode_preface()
        for byte in preface:
            send_all(client, bytes((byte,)))
        assert recv_exact(client, 8) == preface
        client.close()
        future.result(timeout=2)


def test_file_list_then_disconnect_over_real_socket(tmp_path: Path) -> None:
    (tmp_path / "b.bin").write_bytes(b"12")
    (tmp_path / "a.bin").write_bytes(b"1")
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        handshake(client)
        send_frame(client, make_file_list_frame())
        send_frame(client, make_disconnect_frame())

        listing = parse_file_list_response(receive_frame(client))  # type: ignore[arg-type]
        acknowledgement = parse_acknowledgement(receive_frame(client))  # type: ignore[arg-type]
        assert [(item.filename, item.file_size) for item in listing.entries] == [
            ("a.bin", 1),
            ("b.bin", 2),
        ]
        assert acknowledgement.acknowledged_opcode is Opcode.DISCONNECT
        assert acknowledgement.next_offset == 0
        assert client.recv(1) == b""
        future.result(timeout=2)
        client.close()


def test_clean_tcp_close_in_idle_sends_no_ack(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        handshake(client)
        client.close()
        future.result(timeout=2)


def test_peer_close_mid_frame_is_fatal(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        handshake(client)
        send_all(client, struct.pack("!IHH", 8, Opcode.FILE_LIST, 0) + b"ha")
        client.close()
        with pytest.raises((ProtocolError, ConnectionError)) as raised:
            future.result(timeout=2)
        if isinstance(raised.value, ProtocolError):
            assert raised.value.code is ErrorCode.INVALID_FRAME


def test_disconnect_with_payload_returns_error_without_closing_session(
    tmp_path: Path,
) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        handshake(client)
        send_frame(client, Frame(Opcode.DISCONNECT, b"invalid"))
        send_frame(client, make_disconnect_frame())

        error = parse_error(receive_frame(client))  # type: ignore[arg-type]
        acknowledgement = parse_acknowledgement(receive_frame(client))  # type: ignore[arg-type]
        assert error.failed_opcode is Opcode.DISCONNECT
        assert error.error_code is ErrorCode.INVALID_PAYLOAD
        assert acknowledgement.acknowledged_opcode is Opcode.DISCONNECT
        future.result(timeout=2)
        client.close()


def test_unknown_opcode_returns_error_and_stream_remains_synchronized(
    tmp_path: Path,
) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        handshake(client)
        send_all(client, struct.pack("!IHH", 7, 0x7777, 0) + b"abc")
        send_frame(client, make_disconnect_frame())

        error = parse_error(receive_frame(client))  # type: ignore[arg-type]
        acknowledgement = parse_acknowledgement(receive_frame(client))  # type: ignore[arg-type]
        assert error.failed_opcode == 0x7777
        assert error.error_code is ErrorCode.UNSUPPORTED_OPCODE
        assert acknowledgement.acknowledged_opcode is Opcode.DISCONNECT
        future.result(timeout=2)
        client.close()


def test_nonzero_user_id_returns_error_and_session_continues(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        handshake(client)
        send_all(client, struct.pack("!IHH", 4, Opcode.FILE_LIST, 9))
        send_frame(client, make_disconnect_frame())

        error = parse_error(receive_frame(client))  # type: ignore[arg-type]
        assert error.failed_opcode is Opcode.FILE_LIST
        assert error.error_code is ErrorCode.INVALID_USER_ID
        assert parse_acknowledgement(  # type: ignore[arg-type]
            receive_frame(client)
        ).acknowledged_opcode is Opcode.DISCONNECT
        future.result(timeout=2)
        client.close()


def test_unsupported_phase_one_request_returns_error(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, make_config(tmp_path))
        handshake(client)
        send_frame(client, make_file_upload_frame(FileUpload("x.bin", 1)))
        send_frame(client, make_disconnect_frame())

        error = parse_error(receive_frame(client))  # type: ignore[arg-type]
        assert error.failed_opcode is Opcode.FILE_UPLOAD
        assert error.error_code is ErrorCode.UNSUPPORTED_OPCODE
        receive_frame(client)
        future.result(timeout=2)
        client.close()


def test_payload_over_configured_limit_is_fatal(tmp_path: Path) -> None:
    config = make_config(tmp_path, max_payload_bytes=4104)
    with ThreadPoolExecutor(max_workers=1) as executor:
        client, future = start_session(executor, config)
        handshake(client)
        send_all(client, struct.pack("!IHH", 4109, Opcode.FILE_LIST, 0))
        with pytest.raises(ProtocolError) as raised:
            future.result(timeout=2)
        assert raised.value.code is ErrorCode.PAYLOAD_TOO_LARGE
        client.close()


class TwoClientListener:
    def __init__(self, listener: socket.socket) -> None:
        self.listener = listener
        self.accepted = 0

    def accept(self) -> tuple[socket.socket, object]:
        if self.accepted == 2:
            raise KeyboardInterrupt
        result = self.listener.accept()
        self.accepted += 1
        return result

    def close(self) -> None:
        self.listener.close()


def test_listener_accepts_second_client_after_first_client_error(tmp_path: Path) -> None:
    (tmp_path / "available.bin").write_bytes(b"ok")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    address = listener.getsockname()
    wrapped_listener = TwoClientListener(listener)
    config = make_config(tmp_path)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            serve_forever,
            config,
            listener=wrapped_listener,  # type: ignore[arg-type]
        )
        first = socket.create_connection(address, timeout=2)
        send_all(first, b"bad data")
        assert first.recv(1) == b""
        first.close()

        second = socket.create_connection(address, timeout=2)
        second.settimeout(2)
        handshake(second)
        send_frame(second, make_file_list_frame())
        response = parse_file_list_response(receive_frame(second))  # type: ignore[arg-type]
        assert [(item.filename, item.file_size) for item in response.entries] == [
            ("available.bin", 2)
        ]
        send_frame(second, make_disconnect_frame())
        receive_frame(second)
        second.close()
        future.result(timeout=2)

    assert wrapped_listener.accepted == 2


def test_create_listener_binds_ipv4_ephemeral_port(tmp_path: Path) -> None:
    config = AppConfig(
        server=ServerConfig(
            bind_address="127.0.0.1",
            port=0,
            storage_directory=tmp_path,
        )
    )

    listener = create_listener(config)
    try:
        assert listener.family == socket.AF_INET
        assert listener.getsockname()[0] == "127.0.0.1"
        assert listener.getsockname()[1] != 0
    finally:
        listener.close()


class InterruptingListener:
    def __init__(self) -> None:
        self.closed = False

    def accept(self) -> tuple[socket.socket, object]:
        raise KeyboardInterrupt

    def close(self) -> None:
        self.closed = True


def test_serve_forever_creates_storage_and_closes_listener(tmp_path: Path) -> None:
    storage = tmp_path / "new" / "storage"
    listener = InterruptingListener()

    serve_forever(
        make_config(storage),
        listener=listener,  # type: ignore[arg-type]
    )

    assert storage.is_dir()
    assert listener.closed
