"""Streaming server-side handler for Phase 2 DOWNLOAD requests (with Resume support)."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from time import perf_counter
from typing import Protocol

from ..config import AppConfig
from ..messages import (
    ErrorMessage,
    FileChecksum,
    FileChunk,
    FileDownload,
    FileInfo,
    make_error_frame,
    make_file_checksum_frame,
    make_file_chunk_frame,
    make_file_download_frame,
    make_file_info_frame,
    parse_acknowledgement, 
    parse_error,
    parse_file_download,
)
from ..protocol import USER_ID, ErrorCode, Frame, Opcode, ProtocolError
from .namespace import is_internal_file, resolve_namespace_path


class ServerPeer(Protocol):
    """Small adapter expected from the member-1 server session."""

    config: AppConfig
    user_id: int
    storage_directory: Path

    def send(self, frame: Frame) -> None: ...

    def receive(self) -> Frame: ...


@dataclass(frozen=True, slots=True)
class DownloadTransferResult:
    filename: str
    bytes_sent: int
    duration_seconds: float
    success: bool
    checksum_matched: bool | None
    error_code: ErrorCode | None = None

    @property
    def speed_kib_per_second(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return self.bytes_sent / 1024 / self.duration_seconds


def handle_download_frame(
    peer: ServerPeer,
    frame: Frame,
) -> DownloadTransferResult:
    """Decode and execute a top-level ``FILE_DOWNLOAD`` request frame."""

    request = parse_file_download(
        frame,
        peer.config.network.max_payload_bytes,
    )
    return handle_download(peer, request)


def handle_download(
    peer: ServerPeer,
    request: FileDownload,
) -> DownloadTransferResult:
    """Send one file and return structured data suitable for server logging.

    Supports resuming from request.offset if specified.
    """

    started = perf_counter()
    config = peer.config
    maximum = config.network.max_payload_bytes
    try:
        # Reuse the protocol codec as the single source of filename/offset rules.
        make_file_download_frame(
            request,
            maximum,
            user_id=_peer_user_id(peer),
        )
    except ProtocolError as error:
        return _fail(peer, request.filename, 0, started, error.code, str(error))

    path, path_error = _resolve_download_path(
        _peer_storage_directory(peer),
        request.filename,
    )
    if path_error is not None:
        code, message = path_error
        return _fail(peer, request.filename, 0, started, code, message)

    try:
        source = path.open("rb")
    except FileNotFoundError:
        return _fail(
            peer,
            request.filename,
            0,
            started,
            ErrorCode.FILE_NOT_FOUND,
            "file not found",
        )
    except PermissionError:
        return _fail(
            peer,
            request.filename,
            0,
            started,
            ErrorCode.ACCESS_DENIED,
            "cannot open file for reading",
        )
    except OSError as error:
        return _fail(
            peer,
            request.filename,
            0,
            started,
            ErrorCode.FILE_IO_ERROR,
            f"cannot open file: {error}",
        )

    sent = 0
    with source:
        try:
            total_size = os.fstat(source.fileno()).st_size
            offset = request.requested_offset

            # Kiểm tra offset hợp lệ
            if offset < 0 or offset > total_size:
                return _fail(
                    peer,
                    request.filename,
                    0,
                    started,
                    ErrorCode.INVALID_PAYLOAD,
                    f"invalid resume offset {offset} for file size {total_size}",
                )

            # Gửi FILE_INFO đính kèm start_offset
            peer.send(
                make_file_info_frame(
                    FileInfo(request.filename, total_size, start_offset=offset),
                    maximum,
                    user_id=_peer_user_id(peer),
                )
            )
            response = peer.receive()
            response_error = _validate_ack(
                response,
                Opcode.FILE_INFO,
                offset,
                maximum,
            )
            if response_error is not None:
                if response.opcode is not Opcode.ERROR:
                    _send_error(peer, Opcode.FILE_INFO, *response_error)
                code, _message = response_error
                return _result(request.filename, 0, started, False, None, code)

            # Đọc full file để tính checksum gốc, hoặc seek tới offset
            digest = hashlib.sha256()
            # Tính checksum toàn bộ file
            while True:
                chunk = source.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
            full_digest = digest.digest()

            # Seek tới vị trí offset để chuẩn bị gửi data
            source.seek(offset)
            sent = offset

            while True:
                data = source.read(config.network.chunk_size_bytes)
                if not data:
                    break
                peer.send(
                    make_file_chunk_frame(
                        FileChunk(sent, data),
                        config.network.chunk_size_bytes,
                        maximum,
                        user_id=_peer_user_id(peer),
                    )
                )
                sent += len(data)

            if sent != total_size:
                return _fail(
                    peer,
                    request.filename,
                    sent - offset,
                    started,
                    ErrorCode.SIZE_MISMATCH,
                    "file size changed while being read",
                    failed_opcode=Opcode.FILE_CHECKSUM,
                )

            peer.send(
                make_file_checksum_frame(
                    FileChecksum(total_size, full_digest),
                    maximum,
                    user_id=_peer_user_id(peer),
                )
            )
            response = peer.receive()
            response_error = _validate_ack(
                response,
                Opcode.FILE_CHECKSUM,
                total_size,
                maximum,
            )
            if response_error is not None:
                if response.opcode is Opcode.ERROR:
                    remote = parse_error(response, maximum)
                    checksum_matched = (
                        False
                        if remote.error_code is ErrorCode.CHECKSUM_MISMATCH
                        else None
                    )
                    return _result(
                        request.filename,
                        sent - offset,
                        started,
                        False,
                        checksum_matched,
                        remote.error_code,
                    )
                _send_error(peer, Opcode.FILE_CHECKSUM, *response_error)
                code, _message = response_error
                return _result(request.filename, sent - offset, started, False, None, code)

            return _result(request.filename, sent - offset, started, True, True)

        except OSError as error:
            if not isinstance(error, (ConnectionError, TimeoutError)):
                return _fail(
                    peer,
                    request.filename,
                    max(0, sent - request.offset),
                    started,
                    f"file read failed: {error}",
                )
            raise


def _resolve_download_path(
    storage_directory: Path,
    filename: str,
) -> tuple[Path, tuple[ErrorCode, str] | None]:
    if is_internal_file(filename):
        return storage_directory / filename, (
            ErrorCode.FILE_NOT_FOUND,
            "internal files are not available for download",
        )
    try:
        candidate = resolve_namespace_path(
            storage_directory,
            filename,
            must_exist=True,
        )
        return candidate, None
    except ProtocolError as error:
        code = (
            ErrorCode.FILE_NOT_FOUND
            if error.code in {ErrorCode.FILE_NOT_FOUND, ErrorCode.INVALID_FILENAME}
            else error.code
        )
        return storage_directory / filename, (code, str(error))


def _validate_ack(
    frame: Frame,
    expected_opcode: Opcode,
    expected_offset: int,
    max_payload_bytes: int,
) -> tuple[ErrorCode, str] | None:
    if frame.opcode is Opcode.ERROR:
        remote = parse_error(frame, max_payload_bytes)
        return remote.error_code, remote.message
    if frame.opcode is not Opcode.ACK:
        return ErrorCode.INVALID_STATE, f"expected ACK, got {frame.opcode.name}"
    try:
        acknowledgement = parse_acknowledgement(frame, max_payload_bytes)
    except ProtocolError as error:
        return error.code, str(error)
    if acknowledgement.acknowledged_opcode is not expected_opcode:
        return ErrorCode.INVALID_STATE, (
            f"expected ACK for {expected_opcode.name}, got "
            f"{acknowledgement.acknowledged_opcode.name}"
        )
    if acknowledgement.next_offset != expected_offset:
        return ErrorCode.OFFSET_MISMATCH, (
            f"expected next_offset {expected_offset}, got "
            f"{acknowledgement.next_offset}"
        )
    return None


def _send_error(
    peer: ServerPeer,
    failed_opcode: Opcode,
    code: ErrorCode,
    message: str,
) -> None:
    peer.send(
        make_error_frame(
            ErrorMessage(failed_opcode, code, message),
            peer.config.network.max_payload_bytes,
            user_id=_peer_user_id(peer),
        )
    )


def _fail(
    peer: ServerPeer,
    filename: str,
    bytes_sent: int,
    started: float,
    code: ErrorCode,
    message: str,
    *,
    failed_opcode: Opcode = Opcode.FILE_DOWNLOAD,
) -> DownloadTransferResult:
    _send_error(peer, failed_opcode, code, message)
    return _result(filename, bytes_sent, started, False, None, code)


def _result(
    filename: str,
    bytes_sent: int,
    started: float,
    success: bool,
    checksum_matched: bool | None,
    error_code: ErrorCode | None = None,
) -> DownloadTransferResult:
    return DownloadTransferResult(
        filename,
        bytes_sent,
        perf_counter() - started,
        success,
        checksum_matched,
        error_code,
    )


def _peer_user_id(peer: ServerPeer) -> int:
    return getattr(peer, "user_id", USER_ID)


def _peer_storage_directory(peer: ServerPeer) -> Path:
    return getattr(peer, "storage_directory", peer.config.server.storage_directory)
