"""Streaming server-side handler for Phase 1 UPLOAD requests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from ..messages import (
    Acknowledgement,
    ErrorMessage,
    make_acknowledgement_frame,
    make_error_frame,
    parse_file_checksum,
    parse_file_chunk,
    parse_file_upload,
)
from ..protocol import USER_ID, ErrorCode, Frame, Opcode, ProtocolError
from .listing import INTERNAL_FILENAMES
from .namespace import is_internal_file, resolve_namespace_path

if TYPE_CHECKING:
    from .session import ServerSession


@dataclass(frozen=True, slots=True)
class UploadTransferResult:
    filename: str
    bytes_received: int
    duration_seconds: float
    success: bool
    checksum_matched: bool | None
    error_code: ErrorCode | None = None

    @property
    def speed_kib_per_second(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return self.bytes_received / 1024 / self.duration_seconds


def handle_upload(
    session: ServerSession,
    frame: Frame,
) -> UploadTransferResult:
    """Receive, validate, and atomically publish one uploaded file."""

    started = perf_counter()
    maximum = session.config.network.max_payload_bytes
    request = parse_file_upload(frame, maximum)
    filename = request.filename
    received = 0

    storage = _session_storage_directory(session)
    try:
        target = resolve_namespace_path(storage, filename)
    except ProtocolError as error:
        return _fail(
            session,
            filename,
            received,
            started,
            Opcode.FILE_UPLOAD,
            error.code,
            str(error),
        )
    partial = storage / f"{filename}.part"
    try:
        storage.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return _file_failure(
            session,
            filename,
            received,
            started,
            Opcode.FILE_UPLOAD,
            "cannot create the server storage directory",
            error,
        )

    if target.exists() or partial.exists():
        return _fail(
            session,
            filename,
            received,
            started,
            Opcode.FILE_UPLOAD,
            ErrorCode.FILE_EXISTS,
            "destination or partial upload already exists",
        )

    try:
        output = partial.open("xb")
    except FileExistsError:
        return _fail(
            session,
            filename,
            received,
            started,
            Opcode.FILE_UPLOAD,
            ErrorCode.FILE_EXISTS,
            "partial upload already exists",
        )
    except OSError as error:
        return _file_failure(
            session,
            filename,
            received,
            started,
            Opcode.FILE_UPLOAD,
            "cannot create the partial upload",
            error,
        )

    published = False
    digest = hashlib.sha256()
    try:
        with output:
            session.send(
                make_acknowledgement_frame(
                    Acknowledgement(Opcode.FILE_UPLOAD, 0),
                    maximum,
                    user_id=_session_user_id(session),
                )
            )
            while True:
                transfer_frame = session.receive()
                if transfer_frame.opcode is Opcode.FILE_CHUNK:
                    try:
                        chunk = parse_file_chunk(
                            transfer_frame,
                            session.config.network.chunk_size_bytes,
                            maximum,
                        )
                    except ProtocolError as error:
                        return _fail(
                            session,
                            filename,
                            received,
                            started,
                            Opcode.FILE_CHUNK,
                            error.code,
                            str(error),
                        )
                    if chunk.offset != received:
                        return _fail(
                            session,
                            filename,
                            received,
                            started,
                            Opcode.FILE_CHUNK,
                            ErrorCode.OFFSET_MISMATCH,
                            f"expected chunk offset {received}, got {chunk.offset}",
                        )
                    if received + len(chunk.data) > request.total_size:
                        return _fail(
                            session,
                            filename,
                            received,
                            started,
                            Opcode.FILE_CHUNK,
                            ErrorCode.SIZE_MISMATCH,
                            "chunk data exceeds the declared upload size",
                        )
                    try:
                        output.write(chunk.data)
                    except OSError as error:
                        return _file_failure(
                            session,
                            filename,
                            received,
                            started,
                            Opcode.FILE_CHUNK,
                            "cannot write the partial upload",
                            error,
                        )
                    digest.update(chunk.data)
                    received += len(chunk.data)
                    continue

                if transfer_frame.opcode is Opcode.FILE_CHECKSUM:
                    try:
                        checksum = parse_file_checksum(transfer_frame, maximum)
                    except ProtocolError as error:
                        return _fail(
                            session,
                            filename,
                            received,
                            started,
                            Opcode.FILE_CHECKSUM,
                            error.code,
                            str(error),
                        )
                    if (
                        received != request.total_size
                        or checksum.final_size != request.total_size
                    ):
                        return _fail(
                            session,
                            filename,
                            received,
                            started,
                            Opcode.FILE_CHECKSUM,
                            ErrorCode.SIZE_MISMATCH,
                            "received and declared upload sizes do not match",
                        )
                    if checksum.sha256_digest != digest.digest():
                        return _fail(
                            session,
                            filename,
                            received,
                            started,
                            Opcode.FILE_CHECKSUM,
                            ErrorCode.CHECKSUM_MISMATCH,
                            "upload SHA-256 does not match",
                            checksum_matched=False,
                        )
                    try:
                        output.flush()
                        os.fsync(output.fileno())
                    except OSError as error:
                        return _file_failure(
                            session,
                            filename,
                            received,
                            started,
                            Opcode.FILE_CHECKSUM,
                            "cannot flush the partial upload",
                            error,
                        )
                    break

                return _fail(
                    session,
                    filename,
                    received,
                    started,
                    transfer_frame.opcode,
                    ErrorCode.INVALID_STATE,
                    f"unexpected {transfer_frame.opcode.name} during UPLOAD",
                )

        try:
            # Hard-link publication is atomic and refuses to overwrite a target
            # that appears while the transfer is in progress.
            os.link(partial, target)
            published = True
            partial.unlink()
        except FileExistsError:
            if published:
                _remove_quietly(target)
                published = False
            return _fail(
                session,
                filename,
                received,
                started,
                Opcode.FILE_CHECKSUM,
                ErrorCode.FILE_EXISTS,
                "destination appeared while the upload was in progress",
            )
        except OSError as error:
            if published:
                _remove_quietly(target)
                published = False
            return _file_failure(
                session,
                filename,
                received,
                started,
                Opcode.FILE_CHECKSUM,
                "cannot publish the completed upload",
                error,
            )

        session.send(
            make_acknowledgement_frame(
                Acknowledgement(Opcode.FILE_CHECKSUM, received),
                maximum,
                user_id=_session_user_id(session),
            )
        )
        return _result(filename, received, started, True, True)
    finally:
        if not published:
            _remove_quietly(partial)


def _file_failure(
    session: ServerSession,
    filename: str,
    bytes_received: int,
    started: float,
    failed_opcode: Opcode,
    context: str,
    error: OSError,
) -> UploadTransferResult:
    code = (
        ErrorCode.ACCESS_DENIED
        if isinstance(error, PermissionError)
        else ErrorCode.FILE_IO_ERROR
    )
    return _fail(
        session,
        filename,
        bytes_received,
        started,
        failed_opcode,
        code,
        f"{context}: {error}",
    )


def _fail(
    session: ServerSession,
    filename: str,
    bytes_received: int,
    started: float,
    failed_opcode: Opcode,
    code: ErrorCode,
    message: str,
    *,
    checksum_matched: bool | None = None,
) -> UploadTransferResult:
    session.send(
        make_error_frame(
            ErrorMessage(failed_opcode, code, message),
            session.config.network.max_payload_bytes,
            user_id=_session_user_id(session),
        )
    )
    return _result(
        filename,
        bytes_received,
        started,
        False,
        checksum_matched,
        code,
    )


def _result(
    filename: str,
    bytes_received: int,
    started: float,
    success: bool,
    checksum_matched: bool | None,
    error_code: ErrorCode | None = None,
) -> UploadTransferResult:
    return UploadTransferResult(
        filename,
        bytes_received,
        perf_counter() - started,
        success,
        checksum_matched,
        error_code,
    )


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _session_user_id(session: ServerSession) -> int:
    return getattr(session, "user_id", USER_ID)


def _session_storage_directory(session: ServerSession) -> Path:
    return getattr(session, "storage_directory", session.config.server.storage_directory)
