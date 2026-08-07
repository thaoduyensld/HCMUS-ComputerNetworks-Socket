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

from pathlib import Path
import hashlib
from hcmus_socket.common.partial_transfer import (
    get_part_paths,
    save_part_metadata,
    load_part_metadata,
    compute_prefix_hash,
)

from ..protocol import ErrorCode, Frame, Opcode, ProtocolError
from .listing import INTERNAL_FILENAMES

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

    if filename.endswith(".part") or filename.endswith(".part.meta") or filename in INTERNAL_FILENAMES:
        return _fail(
            session,
            filename,
            0,
            started,
            Opcode.FILE_UPLOAD,
            ErrorCode.INVALID_FILENAME,
            "filename is reserved for server-internal use",
        )

    storage = session.config.server.storage_directory
    target = storage / filename
    partial = storage / f"{filename}.part"
    meta_path = storage / f"{filename}.part.meta"

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

    # 1. Xác định Resume Offset & Khôi phục SHA-256 Prefix
    resume_offset = 0
    digest = hashlib.sha256()

    if partial.exists() and meta_path.exists():
        meta = load_part_metadata(meta_path)
        if meta and meta.get("total_size") == request.total_size:
            try:
                actual_bytes = partial.stat().st_size
                meta_bytes = meta.get("uploaded_bytes", 0)
                resume_offset = min(actual_bytes, meta_bytes)

                # Hash lại prefix N byte đầu tiên đã có
                if resume_offset > 0:
                    digest, bytes_hashed = compute_prefix_hash(partial, resume_offset)
                    if bytes_hashed != resume_offset:
                        # File .part bị hỏng giữa chừng, reset về 0
                        resume_offset = 0
                        digest = hashlib.sha256()
            except OSError:
                resume_offset = 0
                digest = hashlib.sha256()

    received = resume_offset

    try:
        # Mở file ở chế độ append binary ("ab") hoặc write binary ("wb")
        output = partial.open("a+b" if partial.exists() else "w+b")
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
            if resume_offset > 0:
                output.seek(resume_offset)
                output.truncate(resume_offset)

            # Gửi ACK chứa resume_offset cho Client
            session.send(
                make_acknowledgement_frame(
                    Acknowledgement(Opcode.FILE_UPLOAD, resume_offset),
                    maximum,
                )
            )

            # Lưu metadata khởi tạo
            save_part_metadata(meta_path, request.total_size, received)

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
                        clean_partial_on_failure = True
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

                    # Persist metadata liên tục để phục hồi offset khi bị ngắt
                    save_part_metadata(meta_path, request.total_size, received)
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


