"""Streaming UPLOAD workflow for the Phase 1 client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path

from ..messages import (
    FileChecksum,
    FileChunk,
    FileUpload,
    make_file_checksum_frame,
    make_file_chunk_frame,
    make_file_upload_frame,
    parse_acknowledgement,
    parse_error,
)
from ..protocol import ErrorCode, Opcode, ProtocolError
from .session import ClientSession, SessionError


ProgressCallback = Callable[[int, int, int], None]


@dataclass(frozen=True, slots=True)
class UploadResult:
    source: Path
    remote_filename: str
    bytes_sent: int
    sha256_digest: bytes


def upload_file(
    session: ClientSession,
    source: str | Path,
    remote_filename: str | None = None,
    *,
    progress: ProgressCallback | None = None,
) -> UploadResult:
    """Upload one file without loading the complete contents into memory."""

    path = Path(source)
    try:
        if not path.is_file():
            raise FileNotFoundError(f"local upload source does not exist: {path}")
        total_size = path.stat().st_size
    except OSError:
        raise

    filename = remote_filename if remote_filename is not None else path.name
    config = session.config
    maximum = config.network.max_payload_bytes
    session.send(
        make_file_upload_frame(
            FileUpload(filename, total_size),
            maximum,
        )
    )
    _expect_ack(session, Opcode.FILE_UPLOAD, 0)

    sent = 0
    digest = hashlib.sha256()
    if progress is not None:
        progress(0, total_size, 100 if total_size == 0 else 0)

    try:
        with path.open("rb") as source_file:
            while True:
                data = source_file.read(config.network.chunk_size_bytes)
                if not data:
                    break
                digest.update(data)
                session.send(
                    make_file_chunk_frame(
                        FileChunk(sent, data),
                        config.network.chunk_size_bytes,
                        maximum,
                    )
                )
                sent += len(data)
                if progress is not None:
                    progress(sent, total_size, int(sent * 100 / total_size))
    except OSError as error:
        session.close(abort=True)
        raise SessionError(f"local upload read failed: {error}") from error

    if sent != total_size:
        session.close(abort=True)
        raise SessionError(
            "local upload source changed size while being read; session aborted"
        )
    checksum = digest.digest()
    session.send(
        make_file_checksum_frame(
            FileChecksum(sent, checksum),
            maximum,
        )
    )
    _expect_ack(session, Opcode.FILE_CHECKSUM, sent)
    return UploadResult(path, filename, sent, checksum)


def _expect_ack(
    session: ClientSession,
    expected_opcode: Opcode,
    expected_offset: int,
) -> None:
    frame = session.receive()
    maximum = session.config.network.max_payload_bytes
    if frame.opcode is Opcode.ERROR:
        error = parse_error(frame, maximum)
        raise ProtocolError(error.error_code, f"server: {error.message}")
    if frame.opcode is not Opcode.ACK:
        raise ProtocolError(
            ErrorCode.INVALID_STATE,
            f"expected ACK for {expected_opcode.name}, got {frame.opcode.name}",
        )
    acknowledgement = parse_acknowledgement(frame, maximum)
    if acknowledgement.acknowledged_opcode is not expected_opcode:
        raise ProtocolError(
            ErrorCode.INVALID_STATE,
            f"expected ACK for {expected_opcode.name}, got ACK for "
            f"{acknowledgement.acknowledged_opcode.name}",
        )
    if acknowledgement.next_offset != expected_offset:
        raise ProtocolError(
            ErrorCode.OFFSET_MISMATCH,
            f"expected ACK next_offset {expected_offset}, got "
            f"{acknowledgement.next_offset}",
        )
