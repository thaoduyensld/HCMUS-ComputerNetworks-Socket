from __future__ import annotations

from collections import deque
import hashlib
from pathlib import Path

import pytest

from hcmus_socket.config import AppConfig, NetworkConfig, ServerConfig
from hcmus_socket.messages import (
    Acknowledgement,
    ErrorMessage,
    FileDownload,
    make_acknowledgement_frame,
    make_error_frame,
    make_file_list_frame,
    parse_error,
    parse_file_checksum,
    parse_file_chunk,
    parse_file_info,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode
from hcmus_socket.server.download import handle_download


class ScriptedPeer:
    def __init__(self, config: AppConfig, responses: list[Frame]) -> None:
        self.config = config
        self.responses = deque(responses)
        self.sent: list[Frame] = []

    def send(self, frame: Frame) -> None:
        self.sent.append(frame)

    def receive(self) -> Frame:
        if not self.responses:
            raise ConnectionError("client disconnected")
        return self.responses.popleft()


def make_config(storage: Path, chunk_size: int = 4096) -> AppConfig:
    return AppConfig(
        server=ServerConfig(storage_directory=storage),
        network=NetworkConfig(1024 * 1024, chunk_size),
    )


@pytest.mark.parametrize("data", [b"", b"binary\x00data\xff" * 1000])
def test_download_streams_chunks_checksum_and_waits_for_final_ack(
    tmp_path: Path,
    data: bytes,
) -> None:
    name = "data.bin"
    (tmp_path / name).write_bytes(data)
    responses = [
        make_acknowledgement_frame(Acknowledgement(Opcode.FILE_INFO, 0)),
        make_acknowledgement_frame(
            Acknowledgement(Opcode.FILE_CHECKSUM, len(data))
        ),
    ]
    peer = ScriptedPeer(make_config(tmp_path), responses)

    result = handle_download(peer, FileDownload(name))

    assert result.success
    assert result.bytes_sent == len(data)
    assert result.checksum_matched is True
    assert result.error_code is None
    assert result.duration_seconds >= 0
    assert result.speed_kib_per_second >= 0
    info = parse_file_info(peer.sent[0])
    assert info.filename == name
    assert info.total_size == len(data)
    chunks = [
        parse_file_chunk(frame, chunk_size_bytes=4096)
        for frame in peer.sent
        if frame.opcode is Opcode.FILE_CHUNK
    ]
    assert b"".join(chunk.data for chunk in chunks) == data
    assert [chunk.offset for chunk in chunks] == list(range(0, len(data), 4096))
    checksum = parse_file_checksum(peer.sent[-1])
    assert checksum.final_size == len(data)
    assert checksum.sha256_digest == hashlib.sha256(data).digest()


def test_missing_file_returns_recoverable_error(tmp_path: Path) -> None:
    peer = ScriptedPeer(make_config(tmp_path), [])

    result = handle_download(peer, FileDownload("missing.bin"))

    assert not result.success
    assert result.error_code is ErrorCode.FILE_NOT_FOUND
    error = parse_error(peer.sent[-1])
    assert error.failed_opcode is Opcode.FILE_DOWNLOAD
    assert error.error_code is ErrorCode.FILE_NOT_FOUND


@pytest.mark.parametrize("filename", ["../secret", "folder/file", "bad.part"])
def test_invalid_or_internal_filename_is_not_downloaded(
    tmp_path: Path,
    filename: str,
) -> None:
    peer = ScriptedPeer(make_config(tmp_path), [])

    result = handle_download(peer, FileDownload(filename))

    assert not result.success
    assert parse_error(peer.sent[-1]).error_code in {
        ErrorCode.INVALID_FILENAME,
        ErrorCode.FILE_NOT_FOUND,
    }


def test_wrong_metadata_ack_returns_invalid_state(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"data")
    peer = ScriptedPeer(make_config(tmp_path), [make_file_list_frame()])

    result = handle_download(peer, FileDownload("data.bin"))

    assert not result.success
    assert result.error_code is ErrorCode.INVALID_STATE
    assert parse_error(peer.sent[-1]).failed_opcode is Opcode.FILE_INFO


def test_wrong_ack_offset_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"data")
    peer = ScriptedPeer(
        make_config(tmp_path),
        [make_acknowledgement_frame(Acknowledgement(Opcode.FILE_INFO, 1))],
    )

    result = handle_download(peer, FileDownload("data.bin"))

    assert not result.success
    assert result.error_code is ErrorCode.OFFSET_MISMATCH
    assert parse_error(peer.sent[-1]).error_code is ErrorCode.OFFSET_MISMATCH


def test_client_checksum_error_is_returned_for_logging(tmp_path: Path) -> None:
    data = b"data"
    (tmp_path / "data.bin").write_bytes(data)
    responses = [
        make_acknowledgement_frame(Acknowledgement(Opcode.FILE_INFO, 0)),
        make_error_frame(
            ErrorMessage(
                Opcode.FILE_CHECKSUM,
                ErrorCode.CHECKSUM_MISMATCH,
                "mismatch",
            )
        ),
    ]
    peer = ScriptedPeer(make_config(tmp_path), responses)

    result = handle_download(peer, FileDownload("data.bin"))

    assert not result.success
    assert result.checksum_matched is False
    assert result.error_code is ErrorCode.CHECKSUM_MISMATCH


def test_client_disconnect_propagates_to_session_owner(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"data")
    peer = ScriptedPeer(make_config(tmp_path), [])

    with pytest.raises(ConnectionError):
        handle_download(peer, FileDownload("data.bin"))
