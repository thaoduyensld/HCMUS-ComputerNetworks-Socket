from __future__ import annotations

from collections import deque
import hashlib
from pathlib import Path

import pytest

from hcmus_socket.client.download import download_file
from hcmus_socket.client.session import SessionError
from hcmus_socket.config import AppConfig, ClientConfig, NetworkConfig
from hcmus_socket.messages import (
    ErrorMessage,
    FileChecksum,
    FileChunk,
    FileInfo,
    make_error_frame,
    make_file_checksum_frame,
    make_file_chunk_frame,
    make_file_info_frame,
    parse_acknowledgement,
    parse_error,
    parse_file_download,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode, ProtocolError


class ScriptedSession:
    def __init__(self, config: AppConfig, frames: list[Frame]) -> None:
        self.config = config
        self.frames = deque(frames)
        self.sent: list[Frame] = []
        self.closed = False

    def send(self, frame: Frame) -> None:
        self.sent.append(frame)

    def receive(self) -> Frame:
        if not self.frames:
            raise ConnectionError("scripted server disconnected")
        return self.frames.popleft()

    def close(self, *, abort: bool = False) -> None:
        del abort
        self.closed = True


def test_download_uses_assigned_session_user_id(tmp_path: Path) -> None:
    frames = [
        make_file_info_frame(FileInfo("empty.bin", 0)),
        make_file_checksum_frame(
            FileChecksum(0, hashlib.sha256(b"").digest())
        ),
    ]
    session = ScriptedSession(make_config(tmp_path), frames)
    session.user_id = 7

    download_file(session, "empty.bin")  # type: ignore[arg-type]

    assert session.sent
    assert all(frame.user_id == 7 for frame in session.sent)


def make_config(download_directory: Path, chunk_size: int = 4096) -> AppConfig:
    return AppConfig(
        client=ClientConfig(download_directory=download_directory),
        network=NetworkConfig(
            max_payload_bytes=1024 * 1024,
            chunk_size_bytes=chunk_size,
        ),
    )


@pytest.mark.parametrize("data", [b"", b"binary\x00data\xff" * 1000])
def test_download_streams_file_and_acknowledges_checksum(
    tmp_path: Path,
    data: bytes,
) -> None:
    name = "data.bin"
    chunk_size = 4096
    frames = [make_file_info_frame(FileInfo(name, len(data)))]
    for offset in range(0, len(data), chunk_size):
        frames.append(
            make_file_chunk_frame(
                FileChunk(offset, data[offset : offset + chunk_size]),
                chunk_size_bytes=chunk_size,
            )
        )
    frames.append(
        make_file_checksum_frame(FileChecksum(len(data), hashlib.sha256(data).digest()))
    )
    progress: list[tuple[int, int, int]] = []
    session = ScriptedSession(make_config(tmp_path, chunk_size), frames)

    result = download_file(  # type: ignore[arg-type]
        session,
        name,
        progress=lambda received, total, percent: progress.append(
            (received, total, percent)
        ),
    )

    assert result.path.read_bytes() == data
    assert result.bytes_received == len(data)
    assert result.sha256_digest == hashlib.sha256(data).digest()
    assert not (tmp_path / f"{name}.part").exists()
    assert parse_file_download(session.sent[0]).filename == name
    assert parse_acknowledgement(session.sent[1]).acknowledged_opcode is Opcode.FILE_INFO
    final_ack = parse_acknowledgement(session.sent[-1])
    assert final_ack.acknowledged_opcode is Opcode.FILE_CHECKSUM
    assert final_ack.next_offset == len(data)
    assert progress[-1] == (len(data), len(data), 100)


def test_server_error_is_reported_without_creating_partial_file(tmp_path: Path) -> None:
    error = make_error_frame(
        ErrorMessage(Opcode.FILE_DOWNLOAD, ErrorCode.FILE_NOT_FOUND, "missing")
    )
    session = ScriptedSession(make_config(tmp_path), [error])

    with pytest.raises(ProtocolError) as raised:
        download_file(session, "missing.bin")  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.FILE_NOT_FOUND
    assert not (tmp_path / "missing.bin.part").exists()


def test_checksum_mismatch_sends_error_and_removes_partial_file(tmp_path: Path) -> None:
    data = b"contents"
    frames = [
        make_file_info_frame(FileInfo("bad.bin", len(data))),
        make_file_chunk_frame(FileChunk(0, data)),
        make_file_checksum_frame(FileChecksum(len(data), bytes(32))),
    ]
    session = ScriptedSession(make_config(tmp_path), frames)

    with pytest.raises(ProtocolError) as raised:
        download_file(session, "bad.bin")  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.CHECKSUM_MISMATCH
    sent_error = parse_error(session.sent[-1])
    assert sent_error.error_code is ErrorCode.CHECKSUM_MISMATCH
    assert not (tmp_path / "bad.bin").exists()
    assert not (tmp_path / "bad.bin.part").exists()


def test_offset_mismatch_sends_error_and_removes_partial_file(tmp_path: Path) -> None:
    frames = [
        make_file_info_frame(FileInfo("offset.bin", 1)),
        make_file_chunk_frame(FileChunk(1, b"x")),
    ]
    session = ScriptedSession(make_config(tmp_path), frames)

    with pytest.raises(ProtocolError) as raised:
        download_file(session, "offset.bin")  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.OFFSET_MISMATCH
    assert parse_error(session.sent[-1]).error_code is ErrorCode.OFFSET_MISMATCH
    assert not (tmp_path / "offset.bin.part").exists()


def test_existing_destination_is_not_overwritten(tmp_path: Path) -> None:
    destination = tmp_path / "exists.bin"
    destination.write_bytes(b"keep")
    session = ScriptedSession(make_config(tmp_path), [])

    with pytest.raises(ProtocolError) as raised:
        download_file(session, destination.name)  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.FILE_EXISTS
    assert destination.read_bytes() == b"keep"
    assert session.sent == []


def test_stale_part_is_removed_before_new_request(tmp_path: Path) -> None:
    part = tmp_path / "missing.bin.part"
    part.write_bytes(b"stale")
    error = make_error_frame(
        ErrorMessage(Opcode.FILE_DOWNLOAD, ErrorCode.FILE_NOT_FOUND, "missing")
    )
    session = ScriptedSession(make_config(tmp_path), [error])

    with pytest.raises(ProtocolError):
        download_file(session, "missing.bin")  # type: ignore[arg-type]

    assert not part.exists()


def test_disconnect_mid_download_removes_partial_file(tmp_path: Path) -> None:
    frames = [
        make_file_info_frame(FileInfo("cut.bin", 100)),
        make_file_chunk_frame(FileChunk(0, b"partial")),
    ]
    session = ScriptedSession(make_config(tmp_path), frames)

    with pytest.raises(ConnectionError):
        download_file(session, "cut.bin")  # type: ignore[arg-type]

    assert not (tmp_path / "cut.bin.part").exists()


def test_directory_creation_error_is_reported_before_metadata_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download_directory = tmp_path / "unavailable"
    session = ScriptedSession(
        make_config(download_directory),
        [make_file_info_frame(FileInfo("data.bin", 0))],
    )
    monkeypatch.setattr(
        Path,
        "mkdir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    with pytest.raises(ProtocolError) as raised:
        download_file(session, "data.bin")  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.ACCESS_DENIED
    error = parse_error(session.sent[-1])
    assert error.failed_opcode is Opcode.FILE_INFO
    assert error.error_code is ErrorCode.ACCESS_DENIED
    assert not session.closed


def test_open_partial_file_error_is_reported_before_metadata_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = ScriptedSession(
        make_config(tmp_path),
        [make_file_info_frame(FileInfo("data.bin", 0))],
    )
    original_open = Path.open

    def failing_open(path: Path, *args: object, **kwargs: object) -> object:
        if path.name.endswith(".part"):
            raise PermissionError("denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(ProtocolError) as raised:
        download_file(session, "data.bin")  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.ACCESS_DENIED
    assert parse_error(session.sent[-1]).failed_opcode is Opcode.FILE_INFO
    assert not session.closed


def test_write_error_reports_failure_and_aborts_unsynchronized_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingOutput:
        def __enter__(self) -> FailingOutput:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def write(self, _data: bytes) -> int:
            raise OSError("disk full")

    session = ScriptedSession(
        make_config(tmp_path),
        [
            make_file_info_frame(FileInfo("data.bin", 1)),
            make_file_chunk_frame(FileChunk(0, b"x")),
        ],
    )
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: FailingOutput())

    with pytest.raises(SessionError):
        download_file(session, "data.bin")  # type: ignore[arg-type]

    error = parse_error(session.sent[-1])
    assert error.failed_opcode is Opcode.FILE_CHUNK
    assert error.error_code is ErrorCode.FILE_IO_ERROR
    assert session.closed


def test_fsync_error_is_reported_while_server_waits_for_final_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"data"
    session = ScriptedSession(
        make_config(tmp_path),
        [
            make_file_info_frame(FileInfo("data.bin", len(data))),
            make_file_chunk_frame(FileChunk(0, data)),
            make_file_checksum_frame(
                FileChecksum(len(data), hashlib.sha256(data).digest())
            ),
        ],
    )
    monkeypatch.setattr("hcmus_socket.client.download.os.fsync", lambda _fd: (_ for _ in ()).throw(OSError("flush failed")))

    with pytest.raises(ProtocolError) as raised:
        download_file(session, "data.bin")  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.FILE_IO_ERROR
    assert parse_error(session.sent[-1]).failed_opcode is Opcode.FILE_CHECKSUM
    assert not session.closed
    assert not (tmp_path / "data.bin.part").exists()


def test_publish_error_is_reported_instead_of_acknowledging_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"data"
    session = ScriptedSession(
        make_config(tmp_path),
        [
            make_file_info_frame(FileInfo("data.bin", len(data))),
            make_file_chunk_frame(FileChunk(0, data)),
            make_file_checksum_frame(
                FileChecksum(len(data), hashlib.sha256(data).digest())
            ),
        ],
    )
    monkeypatch.setattr(
        "hcmus_socket.client.download.os.link",
        lambda *_args: (_ for _ in ()).throw(PermissionError("publish denied")),
    )

    with pytest.raises(ProtocolError) as raised:
        download_file(session, "data.bin")  # type: ignore[arg-type]

    assert raised.value.code is ErrorCode.ACCESS_DENIED
    error = parse_error(session.sent[-1])
    assert error.failed_opcode is Opcode.FILE_CHECKSUM
    assert error.error_code is ErrorCode.ACCESS_DENIED
    assert not session.closed
    assert not (tmp_path / "data.bin").exists()
    assert not (tmp_path / "data.bin.part").exists()
