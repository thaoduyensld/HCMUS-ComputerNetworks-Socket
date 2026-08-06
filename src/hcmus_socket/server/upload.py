"""Server upload handler logic for Phase 1."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..file_transfer import ProgressTracker
from ..messages import (
    Acknowledgement,
    ErrorMessage,
    FileChecksum,
    FileChunk,
    FileUpload,
    decode_message,
    make_acknowledgement_frame,
    make_error_frame,
)
from ..protocol import ErrorCode, Opcode, ProtocolError

if TYPE_CHECKING:
    from .session import ServerSession 

def handle_server_upload(
    session: ServerSession,
    initial_upload_msg: FileUpload,
    storage_dir: Path,
) -> None:
    """
    Xử lý luồng nhận Upload phía Server:
    1. Kiểm tra không ghi đè file cũ.
    2. Gửi ACK chấp nhận FILE_UPLOAD.
    3. Kiểm tra liên tục Size và Offset của từng FileChunk.
    4. Kiểm tra Checksum SHA-256.
    5. Đảm bảo dọn dẹp file .part đầy đủ bằng khối try...finally.
    """
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    filename = initial_upload_msg.filename
    total_size = initial_upload_msg.total_size
    target_filepath = storage_dir / filename
    temp_filepath = storage_dir / f"{filename}.part"

    max_payload = session.config.network.max_payload_bytes

    # --- 1. KHÔNG GHI ĐÈ FILE CŨ ---
    if target_filepath.exists():
        err_msg = ErrorMessage(
            failed_opcode=Opcode.FILE_UPLOAD,
            error_code=ErrorCode.FILE_EXISTS,
            message=f"File '{filename}' đã tồn tại trên Server!",
        )
        session.send(make_error_frame(err_msg, max_payload_bytes=max_payload))
        return

    tracker = ProgressTracker(temp_filepath)
    tracker.open()

    expected_offset = 0

    try:
        # --- 2. PHẢN HỒI ACK MỞ ĐẦU ---
        ack_upload = Acknowledgement(
            acknowledged_opcode=Opcode.FILE_UPLOAD,
            next_offset=0,
        )
        session.send(make_acknowledgement_frame(ack_upload, max_payload_bytes=max_payload))

        # --- 3. NHẬN CÁC FILE_CHUNK VÀ FILE_CHECKSUM ---
        while True:
            frame = session.receive()
            message = decode_message(frame)

            # --- Xử lý Chunk ---
            if isinstance(message, FileChunk):
                # Kiểm tra Offset chính xác (Lỗi 3)
                if message.offset != expected_offset:
                    err_msg = ErrorMessage(
                        failed_opcode=Opcode.FILE_CHUNK,
                        error_code=ErrorCode.INVALID_FRAME,
                        message=f"Lỗi Offset: Kỳ vọng {expected_offset}, nhận được {message.offset}",
                    )
                    session.send(make_error_frame(err_msg, max_payload_bytes=max_payload))
                    return

                # Kiểm tra không ghi vượt quá total_size khai báo (Lỗi 3)
                chunk_len = len(message.data)
                if expected_offset + chunk_len > total_size:
                    err_msg = ErrorMessage(
                        failed_opcode=Opcode.FILE_CHUNK,
                        error_code=ErrorCode.FILE_SIZE_MISMATCH,
                        message="Dữ liệu upload vượt quá tổng kích thước khai báo ban đầu",
                    )
                    session.send(make_error_frame(err_msg, max_payload_bytes=max_payload))
                    return

                tracker.write_chunk(message.offset, message.data)
                expected_offset += chunk_len
                continue

            # --- Xử lý Checksum ---
            if isinstance(message, FileChecksum):
                written_size, computed_digest = tracker.close()

                # Kiểm tra tổng kích thước (Lỗi 3)
                if written_size != total_size or written_size != message.final_size:
                    err_msg = ErrorMessage(
                        failed_opcode=Opcode.FILE_CHECKSUM,
                        error_code=ErrorCode.FILE_SIZE_MISMATCH,
                        message=f"Kích thước không khớp: nhận {written_size} bytes, khai báo {message.final_size} bytes",
                    )
                    session.send(make_error_frame(err_msg, max_payload_bytes=max_payload))
                    return

                # Kiểm tra SHA-256 (Lỗi 3)
                if computed_digest != message.sha256_digest:
                    err_msg = ErrorMessage(
                        failed_opcode=Opcode.FILE_CHECKSUM,
                        error_code=ErrorCode.CHECKSUM_MISMATCH,
                        message="Xác minh SHA-256 thất bại: Dữ liệu bị lỗi trong quá trình truyền",
                    )
                    session.send(make_error_frame(err_msg, max_payload_bytes=max_payload))
                    return

                # Đổi tên file tạm thành chính thức
                temp_filepath.rename(target_filepath)

                # Gửi ACK hoàn tất
                ack_checksum = Acknowledgement(
                    acknowledged_opcode=Opcode.FILE_CHECKSUM,
                    next_offset=written_size,
                )
                session.send(make_acknowledgement_frame(ack_checksum, max_payload_bytes=max_payload))
                print(f"[Server] Upload thành công: {filename} ({written_size} bytes)")
                return

            raise ProtocolError(
                ErrorCode.INVALID_FRAME,
                f"Lệnh không hợp lệ trong luồng Upload: {frame.opcode!r}",
            )

    finally:
        # --- 4. DỌN FILE .PART ĐẦY ĐỦ (Lỗi 4) ---
        tracker.close()
        if temp_filepath.exists():
            try:
                temp_filepath.unlink()
            except OSError:
                pass