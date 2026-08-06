"""Unit tests for client upload logic."""

from __future__ import annotations

from pathlib import Path
import pytest

from hcmus_socket.client.upload import upload_file
from hcmus_socket.config import AppConfig
from hcmus_socket.messages import (
    Acknowledgement,
    ErrorMessage,
    make_acknowledgement_frame,
    make_error_frame,
)
from hcmus_socket.protocol import ErrorCode, Opcode, ProtocolError


class DummyClientSession:
    """Mock ClientSession để test độc lập Client upload."""

    def __init__(self, responses: list[object] | None = None) -> None:
        self.config = AppConfig()
        self.sent_frames = []
        self.responses = responses or []

    def send(self, frame) -> None:
        self.sent_frames.append(frame)

    def receive(self):
        if not self.responses:
            raise ConnectionError("No more mock responses")
        return self.responses.pop(0)


def test_client_upload_file_not_found(tmp_path: Path) -> None:
    """Client phải báo FileNotFoundError nếu file local không tồn tại."""
    session = DummyClientSession()
    missing_file = tmp_path / "non_existent.txt"

    with pytest.raises(FileNotFoundError):
        upload_file(session, missing_file, "remote.txt")


def test_client_upload_server_rejected_with_error(tmp_path: Path) -> None:
    """Client phải ném ProtocolError khi Server phản hồi ErrorMessage (VD: FILE_EXISTS)."""
    source_file = tmp_path / "test.txt"
    source_file.write_bytes(b"hello world")

    # Giả lập Server phản hồi lỗi FILE_EXISTS ngay câu đầu
    err_frame = make_error_frame(
        ErrorMessage(
            failed_opcode=Opcode.FILE_UPLOAD,
            error_code=ErrorCode.FILE_EXISTS,
            message="File unique.txt already exists",
        )
    )
    session = DummyClientSession(responses=[err_frame])

    with pytest.raises(ProtocolError) as exc_info:
        upload_file(session, source_file, "unique.txt")

    assert exc_info.value.code == ErrorCode.FILE_EXISTS
    assert "Server từ chối Upload" in str(exc_info.value) 