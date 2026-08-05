"""Server upload handler logic for Phase 1."""

from __future__ import annotations

import socket
from pathlib import Path

from .file_transfer import ProgressTracker
from .framing import receive_frame, send_frame
from .messages import (
    Acknowledgement,
    ErrorMessage,
    FileChecksum,
    FileChunk,
    FileUpload,
    decode_message,
    make_acknowledgement_frame,
    make_error_frame,
)
from .protocol import ErrorCode, Opcode, ProtocolError


def handle_server_upload(
    sock: socket.socket,
    initial_upload_msg: FileUpload,
    storage_dir: Path,
) -> None:
    """
    Xử lý luồng nhận Upload phía Server:
    1. Tiếp nhận FileUpload metadata.
    2. Gửi ACK chấp nhận.
    3. Nhận liên tục FILE_CHUNK cho đến khi gặp FILE_CHECKSUM.
    4. Ghi file tạm (.part) và tính SHA-256 dồn.
    5. Kiểm tra Checksum, đổi tên file nếu hợp lệ.
    """
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    filename = initial_upload_msg.filename
    target_filepath = storage_dir / filename
    temp_filepath = storage_dir / f"{filename}.part"

    # Khởi tạo tracker quản lý ghi file tạm và hash SHA-256
    tracker = ProgressTracker(temp_filepath)
    tracker.open()

    try:
        # --- BƯỚC 1: Phản hồi ACK cho FILE_UPLOAD ---
        ack_upload = Acknowledgement(
            acknowledged_opcode=Opcode.FILE_UPLOAD,
            next_offset=0,
        )
        send_frame(sock, make_acknowledgement_frame(ack_upload))

        # --- BƯỚC 2: Nhận các FILE_CHUNK và FILE_CHECKSUM ---
        while True:
            frame = receive_frame(sock)
            if frame is None:
                raise ConnectionError("Client ngắt kết nối đột ngột trong khi đang upload")

            message = decode_message(frame)

            # Xử lý khi nhận được Chunk dữ liệu
            if isinstance(message, FileChunk):
                tracker.write_chunk(message.offset, message.data)
                continue

            # Xử lý khi nhận được Checksum kết thúc
            if isinstance(message, FileChecksum):
                written_size, computed_digest = tracker.close()

                # Kiểm tra 1: Tổng kích thước ghi nhận được có khớp không
                if written_size != message.final_size:
                    if temp_filepath.exists():
                        temp_filepath.unlink()
                    err_msg = ErrorMessage(
                        failed_opcode=Opcode.FILE_CHECKSUM,
                        error_code=ErrorCode.FILE_SIZE_MISMATCH,
                        message=f"Kích thước không khớp: nhận được {written_size} bytes, khai báo {message.final_size} bytes",
                    )
                    send_frame(sock, make_error_frame(err_msg))
                    return

                # Kiểm tra 2: SHA-256 digest có trùng khớp không
                if computed_digest != message.sha256_digest:
                    if temp_filepath.exists():
                        temp_filepath.unlink()
                    err_msg = ErrorMessage(
                        failed_opcode=Opcode.FILE_CHECKSUM,
                        error_code=ErrorCode.CHECKSUM_MISMATCH,
                        message="Xác minh SHA-256 thất bại: Dữ liệu bị hỏng trong quá trình truyền",
                    )
                    send_frame(sock, make_error_frame(err_msg))
                    return

                # Checksum hoàn toàn khớp -> Hoàn tất đổi tên file tạm thành chính thức
                if target_filepath.exists():
                    target_filepath.unlink()  # Ghi đè nếu file đã tồn tại
                temp_filepath.rename(target_filepath)

                # Gửi ACK xác nhận upload thành công hoàn toàn
                ack_checksum = Acknowledgement(
                    acknowledged_opcode=Opcode.FILE_CHECKSUM,
                    next_offset=written_size,
                )
                send_frame(sock, make_acknowledgement_frame(ack_checksum))
                print(f"[Server] Đã nhận và lưu thành công file: {filename} ({written_size} bytes)")
                return

            # Nếu nhận gói tin không đúng thứ tự/kỳ vọng
            raise ProtocolError(
                ErrorCode.INVALID_FRAME,
                f"Lệnh không hợp lệ trong luồng Upload: {frame.opcode!r}",
            )

    except Exception:
        # Nếu có bất kỳ lỗi nào xảy ra, luôn đóng và dọn dẹp file tạm
        tracker.close()
        if temp_filepath.exists():
            temp_filepath.unlink()
        raise