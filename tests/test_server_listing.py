from __future__ import annotations

from pathlib import Path

import pytest

from hcmus_socket.config import AppConfig, NetworkConfig, ServerConfig
from hcmus_socket.messages import (
    FileListResponse,
    make_file_list_frame,
    parse_error,
    parse_file_list_response,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode, ProtocolError
from hcmus_socket.server.listing import handle_file_list, list_storage


class CapturingSession:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.frames: list[Frame] = []

    def send(self, frame: Frame) -> None:
        self.frames.append(frame)


def make_config(storage: Path, max_payload_bytes: int = 1024 * 1024) -> AppConfig:
    return AppConfig(
        server=ServerConfig(storage_directory=storage),
        network=NetworkConfig(max_payload_bytes=max_payload_bytes),
    )


def test_empty_storage_returns_empty_response(tmp_path: Path) -> None:
    session = CapturingSession(make_config(tmp_path))

    handle_file_list(session, make_file_list_frame())  # type: ignore[arg-type]

    assert parse_file_list_response(session.frames[0]) == FileListResponse(())


def test_listing_is_sorted_and_contains_exact_file_sizes(tmp_path: Path) -> None:
    (tmp_path / "zéro.bin").write_bytes(b"\x00\xffbinary")
    (tmp_path / "a.txt").write_bytes(b"")
    (tmp_path / "middle.dat").write_bytes(b"1234")

    entries = list_storage(tmp_path)

    assert [(entry.filename, entry.file_size) for entry in entries] == [
        ("a.txt", 0),
        ("middle.dat", 4),
        ("zéro.bin", 8),
    ]


def test_listing_ignores_directories_partial_internal_and_server_log(
    tmp_path: Path,
) -> None:
    (tmp_path / "directory").mkdir()
    (tmp_path / "upload.bin.part").write_bytes(b"partial")
    (tmp_path / ".hcmus_socket.lock").write_text("lock", encoding="utf-8")
    (tmp_path / ".hcmus_socket.log").write_text("log", encoding="utf-8")
    (tmp_path / "server.log").write_text("log", encoding="utf-8")
    (tmp_path / "user.log").write_text("public", encoding="utf-8")

    assert [(entry.filename, entry.file_size) for entry in list_storage(tmp_path)] == [
        ("user.log", 6)
    ]


def test_listing_does_not_follow_file_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("data", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("file symlinks are not available")

    assert [entry.filename for entry in list_storage(tmp_path)] == ["source.txt"]


def test_file_list_rejects_nonempty_request_payload(tmp_path: Path) -> None:
    session = CapturingSession(make_config(tmp_path))

    with pytest.raises(ProtocolError) as raised:
        handle_file_list(  # type: ignore[arg-type]
            session,
            Frame(Opcode.FILE_LIST, b"unexpected"),
        )

    assert raised.value.code is ErrorCode.INVALID_PAYLOAD


def test_missing_storage_returns_file_io_error(tmp_path: Path) -> None:
    session = CapturingSession(make_config(tmp_path / "missing"))

    handle_file_list(session, make_file_list_frame())  # type: ignore[arg-type]

    error = parse_error(session.frames[0])
    assert error.failed_opcode is Opcode.FILE_LIST
    assert error.error_code is ErrorCode.FILE_IO_ERROR


def test_permission_failure_returns_access_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CapturingSession(make_config(tmp_path))

    def deny_access(self: Path) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "iterdir", deny_access)
    handle_file_list(session, make_file_list_frame())  # type: ignore[arg-type]

    assert parse_error(session.frames[0]).error_code is ErrorCode.ACCESS_DENIED


def test_oversized_listing_returns_list_too_large(tmp_path: Path) -> None:
    for index in range(100):
        (tmp_path / f"file-{index:03d}-{'x' * 40}.bin").write_bytes(b"x")
    session = CapturingSession(make_config(tmp_path, max_payload_bytes=4104))

    handle_file_list(session, make_file_list_frame())  # type: ignore[arg-type]

    error = parse_error(session.frames[0])
    assert error.failed_opcode is Opcode.FILE_LIST
    assert error.error_code is ErrorCode.LIST_TOO_LARGE
