"""Streaming DOWNLOAD workflow for the Phase 1 client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from ..messages import (
    Acknowledgement,
    ErrorMessage,
    FileDownload,
    make_acknowledgement_frame,
    make_error_frame,
    make_file_download_frame,
    parse_error,
    parse_file_checksum,
    parse_file_chunk,
    parse_file_info,
)
from ..protocol import ErrorCode, Frame, Opcode, ProtocolError
from .session import ClientSession


ProgressCallback = Callable[[int, int, int], None]


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    bytes_received: int
    sha256_digest: bytes


def download_file(
    session: ClientSession,
    filename: str,
    *,
    progress: ProgressCallback | None = None,
) -> DownloadResult:
    """Download *filename* without loading the complete file into memory."""

    config = session.config
    request = make_file_download_frame(
        FileDownload(filename),
        config.network.max_payload_bytes,
    )
    final_path = config.client.download_directory / filename
    part_path = final_path.with_name(final_path.name + ".part")
    if final_path.exists():
        raise ProtocolError(
            ErrorCode.FILE_EXISTS,
            f"local destination already exists: {final_path}",
        )
    _remove_stale_part(part_path)

    session.send(request)
    first = session.receive()
    if first.opcode is Opcode.ERROR:
        _raise_remote_error(session, first)
    info = parse_file_info(first, config.network.max_payload_bytes)
    if info.filename != filename:
        _send_failure(
            session,
            Opcode.FILE_INFO,
            ErrorCode.INVALID_PAYLOAD,
            "FILE_INFO filename does not match the requested filename",
        )
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            "FILE_INFO filename does not match the requested filename",
        )

    final_path.parent.mkdir(parents=True, exist_ok=True)
    received = 0
    digest = hashlib.sha256()
    committed = False
    try:
        with part_path.open("xb") as output:
            session.send(
                make_acknowledgement_frame(
                    Acknowledgement(Opcode.FILE_INFO, info.start_offset),
                    config.network.max_payload_bytes,
                )
            )
            if progress is not None:
                progress(0, info.total_size, 100 if info.total_size == 0 else 0)

            while True:
                frame = session.receive()
                if frame.opcode is Opcode.ERROR:
                    _raise_remote_error(session, frame)
                if frame.opcode is Opcode.FILE_CHUNK:
                    chunk = parse_file_chunk(
                        frame,
                        config.network.chunk_size_bytes,
                        config.network.max_payload_bytes,
                    )
                    if chunk.offset != received:
                        _send_failure(
                            session,
                            Opcode.FILE_CHUNK,
                            ErrorCode.OFFSET_MISMATCH,
                            f"expected chunk offset {received}, got {chunk.offset}",
                        )
                        raise ProtocolError(
                            ErrorCode.OFFSET_MISMATCH,
                            f"expected chunk offset {received}, got {chunk.offset}",
                        )
                    if received + len(chunk.data) > info.total_size:
                        _send_failure(
                            session,
                            Opcode.FILE_CHUNK,
                            ErrorCode.SIZE_MISMATCH,
                            "chunk data exceeds the advertised file size",
                        )
                        raise ProtocolError(
                            ErrorCode.SIZE_MISMATCH,
                            "chunk data exceeds the advertised file size",
                        )
                    output.write(chunk.data)
                    digest.update(chunk.data)
                    received += len(chunk.data)
                    if progress is not None:
                        percent = (
                            100
                            if info.total_size == 0
                            else int(received * 100 / info.total_size)
                        )
                        progress(received, info.total_size, percent)
                    continue
                if frame.opcode is not Opcode.FILE_CHECKSUM:
                    _send_failure(
                        session,
                        frame.opcode,
                        ErrorCode.INVALID_STATE,
                        f"unexpected {frame.opcode.name} during DOWNLOAD",
                    )
                    raise ProtocolError(
                        ErrorCode.INVALID_STATE,
                        f"unexpected {frame.opcode.name} during DOWNLOAD",
                    )

                checksum = parse_file_checksum(
                    frame,
                    config.network.max_payload_bytes,
                )
                actual_digest = digest.digest()
                if checksum.final_size != info.total_size or received != info.total_size:
                    _send_failure(
                        session,
                        Opcode.FILE_CHECKSUM,
                        ErrorCode.SIZE_MISMATCH,
                        "download size does not match FILE_INFO/FILE_CHECKSUM",
                    )
                    raise ProtocolError(
                        ErrorCode.SIZE_MISMATCH,
                        "download size does not match FILE_INFO/FILE_CHECKSUM",
                    )
                if checksum.sha256_digest != actual_digest:
                    _send_failure(
                        session,
                        Opcode.FILE_CHECKSUM,
                        ErrorCode.CHECKSUM_MISMATCH,
                        "download SHA-256 does not match",
                    )
                    raise ProtocolError(
                        ErrorCode.CHECKSUM_MISMATCH,
                        "download SHA-256 does not match",
                    )
                output.flush()
                os.fsync(output.fileno())
                break

        # Hard-link publication is atomic and refuses to overwrite an existing file.
        os.link(part_path, final_path)
        part_path.unlink()
        committed = True
        session.send(
            make_acknowledgement_frame(
                Acknowledgement(Opcode.FILE_CHECKSUM, received),
                config.network.max_payload_bytes,
            )
        )
        return DownloadResult(final_path, received, actual_digest)
    except BaseException:
        if not committed:
            part_path.unlink(missing_ok=True)
        raise


def _remove_stale_part(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise ProtocolError(
            ErrorCode.FILE_IO_ERROR,
            f"cannot remove stale partial download {path}: {error}",
        ) from error


def _raise_remote_error(session: ClientSession, frame: Frame) -> None:
    error = parse_error(frame, session.config.network.max_payload_bytes)
    raise ProtocolError(error.error_code, f"server: {error.message}")


def _send_failure(
    session: ClientSession,
    failed_opcode: Opcode,
    code: ErrorCode,
    message: str,
) -> None:
    session.send(
        make_error_frame(
            ErrorMessage(failed_opcode, code, message),
            session.config.network.max_payload_bytes,
        )
    )
