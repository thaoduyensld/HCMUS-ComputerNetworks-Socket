from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket

import pytest

from hcmus_socket.client.download import download_file
from hcmus_socket.client.listing import list_files
from hcmus_socket.client.session import ClientSession
from hcmus_socket.config import AppConfig, ClientConfig, NetworkConfig, ServerConfig
from hcmus_socket.framing import receive_frame, send_all
from hcmus_socket.messages import make_file_list_frame, parse_error
from hcmus_socket.protocol import ErrorCode, ProtocolError
from hcmus_socket.server.logger import ServerLogger
from hcmus_socket.server.session import ServerSession, SessionState


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        server=ServerConfig(storage_directory=tmp_path / "storage"),
        client=ClientConfig(download_directory=tmp_path / "downloads"),
        network=NetworkConfig(max_payload_bytes=65536, chunk_size_bytes=4096),
    )


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_session_logs_connection_commands_download_and_disconnect(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    config.server.storage_directory.mkdir()
    contents = bytes(range(256)) * 40
    (config.server.storage_directory / "shared.bin").write_bytes(contents)
    server_socket, client_socket = socket.socketpair()
    log_path = tmp_path / "server.log"
    logger = ServerLogger(log_path)
    server = ServerSession(
        server_socket,
        ("127.0.0.1", 50000),
        config,
        logger=logger,
    )

    def socket_factory(_address: object, *, timeout: float) -> socket.socket:
        client_socket.settimeout(timeout)
        return client_socket

    client = ClientSession(config, socket_factory=socket_factory)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(server.run)
            client.connect()
            list_files(client)
            result = download_file(client, "shared.bin")
            client.disconnect()
            future.result(timeout=5)
    finally:
        logger.close()

    assert result.path.read_bytes() == contents
    events = read_events(log_path)
    assert [event["event"] for event in events] == [
        "connection",
        "command",
        "command",
        "command",
        "disconnection",
    ]
    assert events[0]["result"] == "success"
    assert events[0]["client_ip"] == "127.0.0.1"
    assert [event["command"] for event in events[1:4]] == [
        "FILE_LIST",
        "FILE_DOWNLOAD",
        "DISCONNECT",
    ]
    download = events[2]
    assert download["filename"] == "shared.bin"
    assert download["bytes"] == len(contents)
    assert download["result"] == "success"
    assert download["checksum"] == "match"
    assert events[-1]["result"] == "success"


def test_invalid_handshake_is_logged_without_crashing_logger(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    server_socket, client_socket = socket.socketpair()
    log_path = tmp_path / "server.log"
    logger = ServerLogger(log_path)
    server = ServerSession(
        server_socket,
        ("203.0.113.10", 41000),
        config,
        logger=logger,
    )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(server.run)
            send_all(client_socket, bytes(8))
            with pytest.raises(ProtocolError):
                future.result(timeout=2)
    finally:
        client_socket.close()
        logger.close()

    events = read_events(log_path)
    assert [event["event"] for event in events] == [
        "connection",
        "disconnection",
    ]
    assert events[0]["result"] == "failure"
    assert events[0]["error_code"] == ErrorCode.INVALID_FRAME.name
    assert events[1]["result"] == "failure"


def test_recoverable_list_failure_is_logged_as_failure(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    server_socket, client_socket = socket.socketpair()
    log_path = tmp_path / "server.log"
    logger = ServerLogger(log_path)
    server = ServerSession(
        server_socket,
        ("127.0.0.1", 50000),
        config,
        logger=logger,
    )
    server.state = SessionState.IDLE

    try:
        server._dispatch(make_file_list_frame())
        response = receive_frame(client_socket)
    finally:
        client_socket.close()
        server.close()
        logger.close()

    assert response is not None
    assert parse_error(response).error_code is ErrorCode.FILE_IO_ERROR
    event = read_events(log_path)[0]
    assert event["command"] == "FILE_LIST"
    assert event["result"] == "failure"
    assert event["error_code"] == ErrorCode.FILE_IO_ERROR.name
