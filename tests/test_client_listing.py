from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket

import pytest

from hcmus_socket.client.app import handle_list
from hcmus_socket.client.commands import Command, CommandName
from hcmus_socket.client.download import download_file
from hcmus_socket.client.listing import list_files
from hcmus_socket.client.session import ClientSession
from hcmus_socket.config import AppConfig, ClientConfig, NetworkConfig, ServerConfig
from hcmus_socket.messages import (
    Acknowledgement,
    ErrorMessage,
    FileEntry,
    FileListResponse,
    make_acknowledgement_frame,
    make_error_frame,
    make_file_list_response_frame,
    parse_file_list,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode, ProtocolError
from hcmus_socket.server.session import ServerSession


class ScriptedSession:
    def __init__(self, frames: list[Frame]) -> None:
        self.config = AppConfig()
        self.frames = deque(frames)
        self.sent: list[Frame] = []

    def send(self, frame: Frame) -> None:
        self.sent.append(frame)

    def receive(self) -> Frame:
        return self.frames.popleft()


def response(*entries: tuple[str, int]) -> Frame:
    return make_file_list_response_frame(
        FileListResponse(tuple(FileEntry(name, size) for name, size in entries))
    )


def test_list_empty_directory_returns_valid_empty_result() -> None:
    session = ScriptedSession([response()])

    result = list_files(session)  # type: ignore[arg-type]

    assert result == FileListResponse(())
    parse_file_list(session.sent[0])


def test_list_returns_exact_names_and_sizes_sorted_by_name() -> None:
    session = ScriptedSession(
        [response(("image.png", 204800), ("a.txt", 128), ("middle.bin", 0))]
    )

    result = list_files(session)  # type: ignore[arg-type]

    assert [(entry.filename, entry.file_size) for entry in result.entries] == [
        ("a.txt", 128),
        ("image.png", 204800),
        ("middle.bin", 0),
    ]


def test_list_raises_the_server_error() -> None:
    session = ScriptedSession(
        [
            make_error_frame(
                ErrorMessage(Opcode.FILE_LIST, ErrorCode.ACCESS_DENIED, "denied")
            )
        ]
    )

    with pytest.raises(ProtocolError) as raised:
        list_files(session)  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.ACCESS_DENIED
    assert "denied" in str(raised.value)


def test_list_rejects_error_for_an_unrelated_request() -> None:
    session = ScriptedSession(
        [
            make_error_frame(
                ErrorMessage(
                    Opcode.FILE_DOWNLOAD,
                    ErrorCode.FILE_NOT_FOUND,
                    "missing",
                )
            )
        ]
    )

    with pytest.raises(ProtocolError) as raised:
        list_files(session)  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.INVALID_STATE


def test_list_rejects_unexpected_response_opcode() -> None:
    session = ScriptedSession(
        [make_acknowledgement_frame(Acknowledgement(Opcode.FILE_LIST, 0))]
    )

    with pytest.raises(ProtocolError) as raised:
        list_files(session)  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.INVALID_STATE


def test_session_can_be_reused_after_list() -> None:
    session = ScriptedSession([response(("one.bin", 1)), response(("two.bin", 2))])

    first = list_files(session)  # type: ignore[arg-type]
    second = list_files(session)  # type: ignore[arg-type]

    assert first.entries[0].filename == "one.bin"
    assert second.entries[0].filename == "two.bin"
    assert len(session.sent) == 2


def test_cli_formats_file_names_and_byte_sizes(capsys: pytest.CaptureFixture[str]) -> None:
    session = ScriptedSession([response(("a.txt", 128), ("image.png", 204800))])

    handle_list(session, Command(CommandName.LIST))  # type: ignore[arg-type]

    output = capsys.readouterr().out
    assert "a.txt" in output
    assert "128 bytes" in output
    assert "image.png" in output
    assert "204800 bytes" in output


def test_cli_describes_an_empty_directory(capsys: pytest.CaptureFixture[str]) -> None:
    session = ScriptedSession([response()])

    handle_list(session, Command(CommandName.LIST))  # type: ignore[arg-type]

    assert capsys.readouterr().out.strip() == "No files available."


def test_list_download_list_share_one_real_connection(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    downloads = tmp_path / "downloads"
    storage.mkdir()
    contents = bytes(range(256)) * 40
    (storage / "shared.bin").write_bytes(contents)
    config = AppConfig(
        server=ServerConfig(storage_directory=storage),
        client=ClientConfig(download_directory=downloads),
        network=NetworkConfig(max_payload_bytes=65536, chunk_size_bytes=4096),
    )
    server_socket, client_socket = socket.socketpair()
    server = ServerSession(
        server_socket,
        ("local", 0),
        config,
    )

    def socket_factory(_address: object, *, timeout: float) -> socket.socket:
        client_socket.settimeout(timeout)
        return client_socket

    client = ClientSession(config, socket_factory=socket_factory)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(server.run)
        client.connect()
        first = list_files(client)
        downloaded = download_file(client, "shared.bin")
        second = list_files(client)
        client.disconnect()
        future.result(timeout=5)

    assert first == second
    assert first.entries == (FileEntry("shared.bin", len(contents)),)
    assert downloaded.path.read_bytes() == contents
