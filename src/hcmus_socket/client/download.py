"""Streaming DOWNLOAD workflow for the Phase 2 client (with Resume support)."""

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
from ..protocol import USER_ID, ErrorCode, Frame, Opcode, ProtocolError
from .session import ClientSession, SessionError


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
    """Download *filename* without loading the complete file into memory (supports resume)."""

    config = session.config
    final_path = config.client.download_directory / filename
    part_path = final_path.with_name(final_path.name + ".part")

    if final_path.exists():
        raise ProtocolError(
            ErrorCode.FILE_EXISTS,
            f"local destination already exists: {final_path}",
        )

    # Bọc toàn bộ luồng xử lý vào try để đảm bảo xóa file .part nếu có bất kỳ lỗi nào
    try:
        # 1. Kiểm tra dung lượng file .part hiện tại nếu đang tải dở
        resume_offset = 0
        if part_path.exists():
            try:
                resume_offset = part_path.stat().st_size
            except OSError:
                resume_offset = 0

        # 2. Gửi request FILE_DOWNLOAD đính kèm resume_offset
        request = make_file_download_frame(
            FileDownload(filename, requested_offset=resume_offset),
            config.network.max_payload_bytes,
            user_id=_session_user_id(session),
        )
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

        # Nếu Server điều chỉnh offset
        start_offset = info.start_offset
        if start_offset != resume_offset:
            if start_offset == 0 and part_path.exists():
                _remove_stale_part(part_path)

        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            _raise_local_failure(session, Opcode.FILE_INFO, error, fatal=False)

        digest = hashlib.sha256()
        received = start_offset

        # 3. Đọc dữ liệu cũ của file .part để feed vào digest SHA-256
        if start_offset > 0 and part_path.exists():
            try:
                with part_path.open("rb") as existing_file:
                    bytes_read = 0
                    while bytes_read < start_offset:
                        chunk = existing_file.read(min(65536, start_offset - bytes_read))
                        if not chunk:
                            break
                        digest.update(chunk)
                        bytes_read += len(chunk)
            except OSError as error:
                _remove_stale_part(part_path)
                _raise_local_failure(session, Opcode.FILE_INFO, error, fatal=False)

        # 4. Mở file ở chế độ append ('ab')
        try:
            output = part_path.open("ab")
        except OSError as error:
            _raise_local_failure(session, Opcode.FILE_INFO, error, fatal=False)

        local_error_opcode = Opcode.FILE_CHUNK
        with output:
            session.send(
                make_acknowledgement_frame(
                    Acknowledgement(Opcode.FILE_INFO, start_offset),
                    config.network.max_payload_bytes,
                    user_id=_session_user_id(session),
                )
            )
            if progress is not None:
                percent = (
                    100
                    if info.total_size == 0
                    else int(received * 100 / info.total_size)
                )
                progress(received, info.total_size, percent)

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

                    # --- SỬA 1: Bắt lỗi khi ghi đĩa (fatal=True) ---
                    try:
                        output.write(chunk.data)
                    except OSError as error:
                        _raise_local_failure(session, Opcode.FILE_CHUNK, error, fatal=True)

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
                local_error_opcode = Opcode.FILE_CHECKSUM
                output.flush()

                # --- SỬA 2: Bắt lỗi fsync ---
                try:
                    os.fsync(output.fileno())
                except OSError as error:
                    _raise_local_failure(session, Opcode.FILE_CHECKSUM, error, fatal=False)

                break

        # Tải xong hoàn chỉnh -> Publish file
        published = False
        try:
            os.link(part_path, final_path)
            part_path.unlink(missing_ok=True)
            published = True
        except OSError as error:
            _raise_local_failure(session, Opcode.FILE_CHECKSUM, error, fatal=False)

        session.send(
            make_acknowledgement_frame(
                Acknowledgement(Opcode.FILE_CHECKSUM, received),
                config.network.max_payload_bytes,
                user_id=_session_user_id(session),
            )
        )
        return DownloadResult(final_path, received, actual_digest)

    except ProtocolError:
        _remove_stale_part(part_path)
        raise
    except BaseException:
        # Preserve the partial file so a later DOWNLOAD can resume it.
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
            user_id=_session_user_id(session),
        )
    )


def _raise_local_failure(
    session: ClientSession,
    failed_opcode: Opcode,
    error: OSError,
    *,
    fatal: bool,
) -> None:
    code = (
        ErrorCode.ACCESS_DENIED
        if isinstance(error, PermissionError)
        else ErrorCode.FILE_IO_ERROR
    )
    message = f"local file operation failed: {error}"
    try:
        _send_failure(session, failed_opcode, code, message)
    except (ConnectionError, TimeoutError) as send_error:
        _abort_session(session)
        raise SessionError("connection failed while reporting local file error") from send_error
    if fatal:
        _abort_session(session)
        raise SessionError(message) from error
    raise ProtocolError(code, message) from error


def _abort_session(session: ClientSession) -> None:
    close = getattr(session, "close", None)
    if close is not None:
        close(abort=True)


def _session_user_id(session: ClientSession) -> int:
    return getattr(session, "user_id", USER_ID)
