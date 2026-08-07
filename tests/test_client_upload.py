from __future__ import annotations

from collections import deque
import hashlib
from pathlib import Path

import pytest

from hcmus_socket.client.app import handle_upload
from hcmus_socket.client.commands import Command, CommandName
from hcmus_socket.client.upload import upload_file
from hcmus_socket.client.session import SessionError
from hcmus_socket.config import AppConfig, NetworkConfig
from hcmus_socket.messages import (
    Acknowledgement,
    ErrorMessage,
    make_acknowledgement_frame,
    make_error_frame,
    parse_file_checksum,
    parse_file_chunk,
    parse_file_upload,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode, ProtocolError


class ScriptedSession:
    def __init__(self, responses: list[Frame]) -> None:
        self.config = AppConfig(
            network=NetworkConfig(max_payload_bytes=65536, chunk_size_bytes=4096)
        )
        self.responses = deque(responses)
        self.sent: list[Frame] = []
        self.closed = False

    def send(self, frame: Frame) -> None:
        self.sent.append(frame)

    def receive(self) -> Frame:
        return self.responses.popleft()

    def close(self, *, abort: bool = False) -> None:
        del abort
        self.closed = True


def test_upload_uses_assigned_session_user_id(tmp_path: Path) -> None:
    source = tmp_path / "empty.bin"
    source.write_bytes(b"")
    session = ScriptedSession(
        [
            make_acknowledgement_frame(Acknowledgement(Opcode.FILE_UPLOAD, 0)),
            make_acknowledgement_frame(Acknowledgement(Opcode.FILE_CHECKSUM, 0)),
        ]
    )
    session.user_id = 7

    upload_file(session, source)  # type: ignore[arg-type]

    assert session.sent
    assert all(frame.user_id == 7 for frame in session.sent)


def ack(opcode: Opcode, offset: int) -> Frame:
    return make_acknowledgement_frame(Acknowledgement(opcode, offset))


@pytest.mark.parametrize("contents", [b"", bytes(range(256)) * 40])
def test_upload_streams_configured_chunks_and_checksum(
    tmp_path: Path,
    contents: bytes,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(contents)
    session = ScriptedSession(
        [ack(Opcode.FILE_UPLOAD, 0), ack(Opcode.FILE_CHECKSUM, len(contents))]
    )
    progress: list[tuple[int, int, int]] = []

    result = upload_file(  # type: ignore[arg-type]
        session,
        source,
        "remote.bin",
        progress=lambda sent, total, percent: progress.append(
            (sent, total, percent)
        ),
    )

    metadata = parse_file_upload(session.sent[0])
    chunks = [
        parse_file_chunk(frame, 4096, 65536)
        for frame in session.sent[1:-1]
    ]
    checksum = parse_file_checksum(session.sent[-1])
    assert metadata.filename == "remote.bin"
    assert metadata.total_size == len(contents)
    assert b"".join(chunk.data for chunk in chunks) == contents
    assert [chunk.offset for chunk in chunks] == list(
        range(0, len(contents), 4096)
    )
    assert checksum.final_size == len(contents)
    assert checksum.sha256_digest == hashlib.sha256(contents).digest()
    assert result.bytes_sent == len(contents)
    assert progress[-1] == (len(contents), len(contents), 100)


def test_upload_reports_server_rejection_before_reading_file(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"data")
    session = ScriptedSession(
        [
            make_error_frame(
                ErrorMessage(Opcode.FILE_UPLOAD, ErrorCode.FILE_EXISTS, "exists")
            )
        ]
    )

    with pytest.raises(ProtocolError) as raised:
        upload_file(session, source)  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.FILE_EXISTS
    assert len(session.sent) == 1


def test_upload_rejects_wrong_final_ack_offset(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"data")
    session = ScriptedSession(
        [ack(Opcode.FILE_UPLOAD, 0), ack(Opcode.FILE_CHECKSUM, 3)]
    )

    with pytest.raises(SessionError):
        upload_file(session, source)  # type: ignore[arg-type]

    assert session.closed


def test_cli_upload_uses_local_basename_and_prints_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "nested" / "source.bin"
    source.parent.mkdir()
    source.write_bytes(b"hello")
    session = ScriptedSession(
        [ack(Opcode.FILE_UPLOAD, 0), ack(Opcode.FILE_CHECKSUM, 5)]
    )

    handle_upload(  # type: ignore[arg-type]
        session,
        Command(CommandName.UPLOAD, str(source)),
    )

    assert parse_file_upload(session.sent[0]).filename == "source.bin"
    output = capsys.readouterr().out
    assert "Uploaded source.bin" in output
    assert "5 bytes" in output
