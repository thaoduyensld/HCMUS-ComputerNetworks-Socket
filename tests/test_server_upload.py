from __future__ import annotations

from collections import deque
import hashlib
from pathlib import Path

from hcmus_socket.config import AppConfig, NetworkConfig, ServerConfig
from hcmus_socket.messages import (
    FileChecksum,
    FileChunk,
    FileUpload,
    make_file_checksum_frame,
    make_file_chunk_frame,
    make_file_list_frame,
    make_file_upload_frame,
    parse_acknowledgement,
    parse_error,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode
from hcmus_socket.server.upload import handle_upload


class ScriptedSession:
    def __init__(self, storage: Path, frames: list[Frame]) -> None:
        self.config = AppConfig(
            server=ServerConfig(storage_directory=storage),
            network=NetworkConfig(max_payload_bytes=65536, chunk_size_bytes=4096),
        )
        self.frames = deque(frames)
        self.sent: list[Frame] = []

    def send(self, frame: Frame) -> None:
        self.sent.append(frame)

    def receive(self) -> Frame:
        return self.frames.popleft()


def upload_frame(filename: str, size: int) -> Frame:
    return make_file_upload_frame(FileUpload(filename, size), 65536)


def test_upload_streams_and_atomically_publishes_file(tmp_path: Path) -> None:
    contents = bytes(range(256)) * 40
    frames = [
        make_file_chunk_frame(FileChunk(0, contents[:4096]), 4096, 65536),
        make_file_chunk_frame(FileChunk(4096, contents[4096:8192]), 4096, 65536),
        make_file_chunk_frame(FileChunk(8192, contents[8192:]), 4096, 65536),
        make_file_checksum_frame(
            FileChecksum(len(contents), hashlib.sha256(contents).digest()),
            65536,
        ),
    ]
    session = ScriptedSession(tmp_path, frames)

    result = handle_upload(  # type: ignore[arg-type]
        session,
        upload_frame("data.bin", len(contents)),
    )

    assert result.success
    assert result.bytes_received == len(contents)
    assert result.checksum_matched
    assert (tmp_path / "data.bin").read_bytes() == contents
    assert not (tmp_path / "data.bin.part").exists()
    assert parse_acknowledgement(session.sent[0]).acknowledged_opcode is Opcode.FILE_UPLOAD
    final_ack = parse_acknowledgement(session.sent[-1])
    assert final_ack.acknowledged_opcode is Opcode.FILE_CHECKSUM
    assert final_ack.next_offset == len(contents)


def test_upload_rejects_existing_destination_without_modifying_it(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"keep")
    session = ScriptedSession(tmp_path, [])

    result = handle_upload(  # type: ignore[arg-type]
        session,
        upload_frame("data.bin", 1),
    )

    assert not result.success
    assert result.error_code is ErrorCode.FILE_EXISTS
    assert parse_error(session.sent[0]).error_code is ErrorCode.FILE_EXISTS
    assert target.read_bytes() == b"keep"


def test_upload_rejects_existing_partial_without_deleting_it(tmp_path: Path) -> None:
    partial = tmp_path / "data.bin.part"
    partial.write_bytes(b"another transfer")
    session = ScriptedSession(tmp_path, [])

    result = handle_upload(  # type: ignore[arg-type]
        session,
        upload_frame("data.bin", 1),
    )

    assert result.error_code is ErrorCode.FILE_EXISTS
    assert partial.read_bytes() == b"another transfer"


def test_upload_offset_mismatch_sends_error_and_removes_partial(tmp_path: Path) -> None:
    session = ScriptedSession(
        tmp_path,
        [make_file_chunk_frame(FileChunk(1, b"x"), 4096, 65536)],
    )

    result = handle_upload(  # type: ignore[arg-type]
        session,
        upload_frame("data.bin", 1),
    )

    assert result.error_code is ErrorCode.OFFSET_MISMATCH
    error = parse_error(session.sent[-1])
    assert error.failed_opcode is Opcode.FILE_CHUNK
    assert error.error_code is ErrorCode.OFFSET_MISMATCH
    assert not (tmp_path / "data.bin.part").exists()


def test_upload_size_mismatch_sends_error_and_removes_partial(tmp_path: Path) -> None:
    session = ScriptedSession(
        tmp_path,
        [make_file_checksum_frame(FileChecksum(0, hashlib.sha256().digest()))],
    )

    result = handle_upload(  # type: ignore[arg-type]
        session,
        upload_frame("data.bin", 1),
    )

    assert result.error_code is ErrorCode.SIZE_MISMATCH
    assert parse_error(session.sent[-1]).error_code is ErrorCode.SIZE_MISMATCH
    assert not (tmp_path / "data.bin.part").exists()


def test_upload_checksum_mismatch_sends_error_and_removes_partial(
    tmp_path: Path,
) -> None:
    session = ScriptedSession(
        tmp_path,
        [
            make_file_chunk_frame(FileChunk(0, b"x"), 4096, 65536),
            make_file_checksum_frame(FileChecksum(1, bytes(32))),
        ],
    )

    result = handle_upload(  # type: ignore[arg-type]
        session,
        upload_frame("data.bin", 1),
    )

    assert result.error_code is ErrorCode.CHECKSUM_MISMATCH
    assert result.checksum_matched is False
    assert parse_error(session.sent[-1]).error_code is ErrorCode.CHECKSUM_MISMATCH
    assert not (tmp_path / "data.bin.part").exists()


def test_upload_rejects_message_that_is_invalid_in_transfer_state(
    tmp_path: Path,
) -> None:
    session = ScriptedSession(tmp_path, [make_file_list_frame()])

    result = handle_upload(  # type: ignore[arg-type]
        session,
        upload_frame("data.bin", 1),
    )

    error = parse_error(session.sent[-1])
    assert result.error_code is ErrorCode.INVALID_STATE
    assert error.failed_opcode is Opcode.FILE_LIST
    assert error.error_code is ErrorCode.INVALID_STATE
    assert not (tmp_path / "data.bin.part").exists()


def test_upload_rejects_reserved_internal_filename(tmp_path: Path) -> None:
    session = ScriptedSession(tmp_path, [])

    result = handle_upload(  # type: ignore[arg-type]
        session,
        upload_frame("server.log", 0),
    )

    assert result.error_code is ErrorCode.INVALID_FILENAME
    assert parse_error(session.sent[0]).error_code is ErrorCode.INVALID_FILENAME
