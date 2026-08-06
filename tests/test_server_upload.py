"""Unit tests for server upload handler."""

from __future__ import annotations

from pathlib import Path
import pytest

from hcmus_socket.config import AppConfig
from hcmus_socket.messages import (
    FileChecksum,
    FileChunk,
    FileUpload,
    decode_message,
    make_file_checksum_frame,
    make_file_chunk_frame,
)
from hcmus_socket.protocol import ErrorCode, Opcode
from hcmus_socket.server.upload import handle_server_upload


class DummyServerSession:
    """Mock ServerSession để capture các khung tin phản hồi của Server."""

    def __init__(self) -> None:
        self.config = AppConfig()
        self.sent_frames = []
        self.incoming_frames = []

    def send(self, frame) -> None:
        self.sent_frames.append(frame)

    def receive(self):
        if not self.incoming_frames:
            raise ConnectionError("No more incoming frames")
        return self.incoming_frames.pop(0)


def test_server_upload_rejects_existing_file(tmp_path: Path) -> None:
    """Server phải phản hồi FILE_EXISTS và dừng nếu file đã tồn tại trên Server."""
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    filename = "existing.txt"
    (storage_dir / filename).write_bytes(b"old content")

    session = DummyServerSession()
    upload_msg = FileUpload(filename=filename, total_size=100, start_offset=0)

    # Thực thi handler
    handle_server_upload(session, upload_msg, storage_dir)

    # Server không được tạo file .part
    assert not (storage_dir / f"{filename}.part").exists()

    # Phải gửi Error Frame báo FILE_EXISTS
    assert len(session.sent_frames) == 1
    err_msg = decode_message(session.sent_frames[0])
    assert err_msg.error_code == ErrorCode.FILE_EXISTS


def test_server_upload_invalid_offset(tmp_path: Path) -> None:
    """Server phải báo lỗi INVALID_FRAME và dọn file .part nếu Offset gửi sang bị lệch."""
    storage_dir = tmp_path / "storage"
    session = DummyServerSession()

    filename = "offset_test.bin"
    upload_msg = FileUpload(filename=filename, total_size=10, start_offset=0)

    # Giả lập client gửi chunk với offset = 5 (thay vì 0)
    bad_chunk_frame = make_file_chunk_frame(FileChunk(offset=5, data=b"12345"))
    session.incoming_frames.append(bad_chunk_frame)

    handle_server_upload(session, upload_msg, storage_dir)

    # Đảm bảo file .part đã được dọn sạch
    assert not (storage_dir / f"{filename}.part").exists()

    # Kiểm tra frame lỗi trả về
    assert len(session.sent_frames) == 2  # ACK FILE_UPLOAD + Error Frame
    err_msg = decode_message(session.sent_frames[1])
    assert err_msg.error_code == ErrorCode.INVALID_FRAME


def test_server_upload_checksum_mismatch(tmp_path: Path) -> None:
    """Server phải phát hiện SHA-256 bị sai, báo CHECKSUM_MISMATCH và dọn file .part."""
    storage_dir = tmp_path / "storage"
    session = DummyServerSession()

    filename = "corrupted.txt"
    data = b"Hello Server"
    upload_msg = FileUpload(filename=filename, total_size=len(data), start_offset=0)

    # Khung Chunk chứa data
    chunk_frame = make_file_chunk_frame(FileChunk(offset=0, data=data))
    # Khung Checksum gửi sai digest (ví dụ 32 bytes 0x00)
    bad_checksum_frame = make_file_checksum_frame(
        FileChecksum(final_size=len(data), sha256_digest=b"\x00" * 32)
    )

    session.incoming_frames.extend([chunk_frame, bad_checksum_frame])

    handle_server_upload(session, upload_msg, storage_dir)

    # Dọn dẹp cả file đích lẫn file .part
    assert not (storage_dir / filename).exists()
    assert not (storage_dir / f"{filename}.part").exists()

    # Kiểm tra Error Message
    err_msg = decode_message(session.sent_frames[-1])
    assert err_msg.error_code == ErrorCode.CHECKSUM_MISMATCH 