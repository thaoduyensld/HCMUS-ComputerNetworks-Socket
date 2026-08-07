"""Streaming server-side handler for Phase 1 UPLOAD requests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from time import perf_counter
from typing import Any, TYPE_CHECKING

from ..messages import (
    Acknowledgement,
    ErrorMessage,
    make_acknowledgement_frame,
    make_error_frame,
    parse_file_checksum,
    parse_file_chunk,
    parse_file_upload,
)
from ..common.partial_transfer import (
    PART_METADATA_VERSION,
    compute_prefix_hash,
    get_part_paths,
    load_part_metadata,
    save_part_metadata,
)

from ..protocol import USER_ID, ErrorCode, Frame, Opcode, ProtocolError
from .cleanup import cleanup_expired_partial_pair
from .namespace import resolve_namespace_path

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
    """Receive, validate, resume (if partial exists), and atomically publish one uploaded file."""

    started = perf_counter()
    maximum = session.config.network.max_payload_bytes
    request = parse_file_upload(frame, maximum)
    filename = request.filename

    storage = _session_storage_directory(session)
    try:
        target = resolve_namespace_path(storage, filename)
    except ProtocolError as error:
        return _fail(
            session,
            filename,
            0,
            started,
            Opcode.FILE_UPLOAD,
            error.code,
            str(error),
        )
    partial, meta_path = get_part_paths(target)

    try:
        storage.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return _file_failure(
            session,
            filename,
            0,
            started,
            Opcode.FILE_UPLOAD,
            "cannot create the server storage directory",
            error,
        )

    # Nếu file chính thức đã tồn tại -> Từ chối, tuyệt đối không ghi đè
    if target.exists():
        return _fail(
            session,
            filename,
            0,
            started,
            Opcode.FILE_UPLOAD,
            ErrorCode.FILE_EXISTS,
            "destination file already exists",
        )

    cleanup_expired_partial_pair(
        partial,
        meta_path,
        session.config.server.partial_ttl_seconds,
    )

    username = _session_username(session)
    resume_offset = 0
    digest = hashlib.sha256()

    if partial.is_symlink() or meta_path.is_symlink():
        _remove_quietly(partial)
        _remove_quietly(meta_path)
    elif partial.exists() != meta_path.exists():
        _remove_quietly(partial)
        _remove_quietly(meta_path)
    elif partial.exists():
        meta = load_part_metadata(meta_path)
        if meta is None or not _valid_metadata_shape(meta):
            _remove_quietly(partial)
            _remove_quietly(meta_path)
        elif not _metadata_identity_matches(
            meta,
            username=username,
            filename=filename,
            total_size=request.total_size,
        ):
            if request.start_offset != 0:
                return _fail(
                    session,
                    filename,
                    0,
                    started,
                    Opcode.FILE_UPLOAD,
                    ErrorCode.RESUME_METADATA_MISMATCH,
                    "partial upload metadata does not match the request",
                )
            _remove_quietly(partial)
            _remove_quietly(meta_path)
        else:
            try:
                actual_bytes = partial.stat().st_size
            except OSError as error:
                return _file_failure(
                    session,
                    filename,
                    0,
                    started,
                    Opcode.FILE_UPLOAD,
                    "cannot inspect the partial upload",
                    error,
                )
            meta_bytes = meta["uploaded_bytes"]
            if actual_bytes > request.total_size or meta_bytes > actual_bytes:
                _remove_quietly(partial)
                _remove_quietly(meta_path)
                return _fail(
                    session,
                    filename,
                    0,
                    started,
                    Opcode.FILE_UPLOAD,
                    ErrorCode.RESUME_METADATA_MISMATCH,
                    "partial upload size is inconsistent with its metadata",
                )
            resume_offset = meta_bytes
            if resume_offset:
                try:
                    digest, bytes_hashed = compute_prefix_hash(partial, resume_offset)
                except OSError as error:
                    return _file_failure(
                        session,
                        filename,
                        0,
                        started,
                        Opcode.FILE_UPLOAD,
                        "cannot hash the partial upload",
                        error,
                    )
                if bytes_hashed != resume_offset:
                    _remove_quietly(partial)
                    _remove_quietly(meta_path)
                    return _fail(
                        session,
                        filename,
                        0,
                        started,
                        Opcode.FILE_UPLOAD,
                        ErrorCode.RESUME_METADATA_MISMATCH,
                        "partial upload prefix is shorter than its metadata",
                    )

    received = resume_offset

    try:
        output = partial.open("r+b" if partial.exists() else "w+b")
    except OSError as error:
        return _file_failure(
            session,
            filename,
            received,
            started,
            Opcode.FILE_UPLOAD,
            "cannot open the partial upload file",
            error,
        )

    published = False
    clean_partial_on_failure = False  # Mặc định giữ .part để Resume nếu rớt mạng

    try:
        with output:
            output.seek(resume_offset)
            output.truncate(resume_offset)
            save_part_metadata(
                meta_path,
                request.total_size,
                received,
                username=username,
                filename=filename,
            )
            session.send(
                make_acknowledgement_frame(
                    Acknowledgement(Opcode.FILE_UPLOAD, resume_offset),
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
                        clean_partial_on_failure = True
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
                        clean_partial_on_failure = True
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
                        output.flush()
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

                    # Pace the next socket read; TCP backpressure slows the sender.
                    _consume_bandwidth(session, len(chunk.data))

                    save_part_metadata(
                        meta_path,
                        request.total_size,
                        received,
                        username=username,
                        filename=filename,
                    )
                    continue

                if transfer_frame.opcode is Opcode.FILE_CHECKSUM:
                    try:
                        checksum = parse_file_checksum(transfer_frame, maximum)
                    except ProtocolError as error:
                        clean_partial_on_failure = True
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
                        clean_partial_on_failure = True
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
                        clean_partial_on_failure = True
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

                clean_partial_on_failure = True
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
            # Atomic publication
            os.link(partial, target)
            published = True
            partial.unlink()
            _remove_quietly(meta_path)  # Dọn dẹp file metadata sau khi hoàn tất
        except FileExistsError:
            if published:
                _remove_quietly(target)
                published = False
            clean_partial_on_failure = True
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
        # Chỉ dọn .part/.meta nếu publish thành công HOẶC gặp lỗi nghiệp vụ nghiêm trọng (không thể resume)
        if published or clean_partial_on_failure:
            _remove_quietly(partial)
            _remove_quietly(meta_path) 


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


def _session_username(session: ServerSession) -> str:
    return getattr(session, "username", None) or ""


def _valid_metadata_shape(metadata: dict[str, Any]) -> bool:
    uploaded = metadata.get("uploaded_bytes")
    updated_at = metadata.get("updated_at_unix")
    return (
        metadata.get("version") == PART_METADATA_VERSION
        and isinstance(metadata.get("username"), str)
        and isinstance(metadata.get("filename"), str)
        and isinstance(metadata.get("total_size"), int)
        and not isinstance(metadata.get("total_size"), bool)
        and isinstance(uploaded, int)
        and not isinstance(uploaded, bool)
        and uploaded >= 0
        and isinstance(updated_at, (int, float))
        and not isinstance(updated_at, bool)
        and updated_at >= 0
    )


def _metadata_identity_matches(
    metadata: dict[str, Any],
    *,
    username: str,
    filename: str,
    total_size: int,
) -> bool:
    return (
        metadata["username"] == username
        and metadata["filename"] == filename
        and metadata["total_size"] == total_size
        and metadata["uploaded_bytes"] <= total_size
    )


def _session_storage_directory(session: ServerSession) -> Path:
    return getattr(session, "storage_directory", session.config.server.storage_directory)


def _consume_bandwidth(session: ServerSession, amount: int) -> float:
    consume = getattr(session, "consume_bandwidth", None)
    return 0.0 if consume is None else consume(amount)
