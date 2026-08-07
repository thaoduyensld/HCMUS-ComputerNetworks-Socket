from __future__ import annotations

from collections import deque
import hashlib
from pathlib import Path

import pytest

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
from hcmus_socket.common.partial_transfer import save_part_metadata 


class ScriptedSession:
    def __init__(self, storage: Path, frames: list[Frame]) -> None:
        self.config = AppConfig(
            server=ServerConfig(storage_directory=storage),
            network=NetworkConfig(max_payload_bytes=65536, chunk_size_bytes=4096),
        )
        self.frames = deque(frames)
        self.sent: list[Frame] = []
        self.consumed: list[int] = []

    def send(self, frame: Frame) -> None:
        self.sent.append(frame)

    def receive(self) -> Frame:
        return self.frames.popleft()

    def consume_bandwidth(self, amount: int) -> float:
        self.consumed.append(amount)
        return 0.0


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
    assert session.consumed == [4096, 4096, len(contents) - 8192]
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

@pytest.mark.skip(reason="Phase 1 test obsolete: Phase 2 now resumes partial uploads instead of rejecting them.")
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

def test_upload_resume_interrupted(tmp_path: Path) -> None:
    # 1. Giả lập một file .part và .part.meta dở dang trên Server (đã upload được 100 bytes)
    filename = "test_resume.txt"
    part_file = tmp_path / f"{filename}.part"
    meta_file = tmp_path / f"{filename}.part.meta"

    full_data = b"A" * 100 + b"B" * 100
    total_size = len(full_data)

    # Server đã có 100 bytes đầu
    part_file.write_bytes(full_data[:100])
    save_part_metadata(meta_file, total_size=total_size, uploaded_bytes=100)

    # Hash toàn bộ file chuẩn
    full_hash = hashlib.sha256(full_data).digest()

    # 2. Tạo ScriptedSession với các frame Client gửi tiếp: Chunk (từ 100) -> Checksum
    session = ScriptedSession(
        tmp_path,
        [
            make_file_chunk_frame(FileChunk(offset=100, data=full_data[100:]), 8192, 65536),
            make_file_checksum_frame(FileChecksum(final_size=total_size, sha256_digest=full_hash), 65536),
        ],
    )

    # 3. Chạy handle_upload với request FILE_UPLOAD ban đầu
    upload_frame = make_file_upload_frame(FileUpload(filename, total_size), 65536)
    result = handle_upload(session, upload_frame)

    # 4. Kiểm tra kết quả: File hoàn thành, các file .part/.meta được dọn dẹp
    assert result.success is True
    assert (tmp_path / filename).exists()
    assert (tmp_path / filename).read_bytes() == full_data
    assert not part_file.exists()
    assert not meta_file.exists()
