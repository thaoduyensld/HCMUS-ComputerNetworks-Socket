from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket

import pytest

from hcmus_socket.client.download import download_file
from hcmus_socket.client.listing import list_files
from hcmus_socket.client.session import ClientSession
from hcmus_socket.client.upload import upload_file
from hcmus_socket.config import AppConfig, ClientConfig, NetworkConfig, ServerConfig
from hcmus_socket.framing import encode_preface, receive_frame, recv_exact, send_all, send_frame
from hcmus_socket.messages import (
    FileChunk,
    FileUpload,
    make_file_chunk_frame,
    make_file_upload_frame,
    parse_acknowledgement,
)
from hcmus_socket.protocol import ErrorCode, Opcode, ProtocolError
from hcmus_socket.server.logger import ServerLogger
from hcmus_socket.server.session import ServerSession


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        server=ServerConfig(storage_directory=tmp_path / "storage"),
        client=ClientConfig(download_directory=tmp_path / "downloads"),
        network=NetworkConfig(max_payload_bytes=65536, chunk_size_bytes=4096),
    )


def make_client(
    config: AppConfig,
    client_socket: socket.socket,
) -> ClientSession:
    def socket_factory(_address: object, *, timeout: float) -> socket.socket:
        client_socket.settimeout(timeout)
        return client_socket

    return ClientSession(config, socket_factory=socket_factory)


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    "contents",
    [b"", bytes(range(256)) * 40],
    ids=["empty", "binary"],
)
def test_list_upload_list_download_list_share_one_tcp_session(
    tmp_path: Path,
    contents: bytes,
) -> None:
    config = make_config(tmp_path)
    config.server.storage_directory.mkdir()
    source = tmp_path / "source.bin"
    source.write_bytes(contents)
    server_socket, client_socket = socket.socketpair()
    log_path = tmp_path / "server.log"
    logger = ServerLogger(log_path)
    server = ServerSession(
        server_socket,
        ("127.0.0.1", 50000),
        config,
        logger=logger,
    )
    client = make_client(config, client_socket)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(server.run)
            try:
                client.connect()
                assert list_files(client).entries == ()
                uploaded = upload_file(client, source)
                with pytest.raises(ProtocolError) as raised:
                    upload_file(client, source)
                assert raised.value.code is ErrorCode.FILE_EXISTS
                listed = list_files(client)
                downloaded = download_file(client, source.name)
                assert list_files(client) == listed
                client.disconnect()
                future.result(timeout=5)
            finally:
                client.close(abort=True)
    finally:
        logger.close()

    assert uploaded.bytes_sent == len(contents)
    assert [(entry.filename, entry.file_size) for entry in listed.entries] == [
        (source.name, len(contents))
    ]
    assert downloaded.path.read_bytes() == contents
    assert (config.server.storage_directory / source.name).read_bytes() == contents
    assert not (config.server.storage_directory / f"{source.name}.part").exists()

    events = read_events(log_path)
    commands = [event for event in events if event["event"] == "command"]
    assert [event["command"] for event in commands] == [
        "FILE_LIST",
        "FILE_UPLOAD",
        "FILE_UPLOAD",
        "FILE_LIST",
        "FILE_DOWNLOAD",
        "FILE_LIST",
        "DISCONNECT",
    ]
    successful_upload = commands[1]
    assert successful_upload["filename"] == source.name
    assert successful_upload["bytes"] == len(contents)
    assert successful_upload["checksum"] == "match"
    assert successful_upload["result"] == "success"
    assert commands[2]["error_code"] == ErrorCode.FILE_EXISTS.name


def test_disconnect_mid_upload_removes_partial_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    server_socket, client_socket = socket.socketpair()
    client_socket.settimeout(2)
    server = ServerSession(server_socket, ("127.0.0.1", 50000), config)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(server.run)
        send_all(client_socket, encode_preface())
        assert recv_exact(client_socket, 8) == encode_preface()
        send_frame(client_socket, make_file_upload_frame(FileUpload("cut.bin", 10)))
        acknowledgement = parse_acknowledgement(receive_frame(client_socket))  # type: ignore[arg-type]
        assert acknowledgement.acknowledged_opcode is Opcode.FILE_UPLOAD
        send_frame(client_socket, make_file_chunk_frame(FileChunk(0, b"partial")))
        client_socket.close()
        with pytest.raises(ConnectionError):
            future.result(timeout=2)

    assert not (config.server.storage_directory / "cut.bin").exists()
    assert (config.server.storage_directory / "cut.bin.part").exists() 
