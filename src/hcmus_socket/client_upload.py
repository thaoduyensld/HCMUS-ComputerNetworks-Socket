"""Client upload logic for Phase 1."""

from __future__ import annotations

import socket
from pathlib import Path

from .file_transfer import read_file_chunks
from .framing import receive_frame, send_frame
from .messages import (
    Acknowledgement,
    ErrorMessage,
    FileChecksum,
    FileUpload,
    decode_message,
    make_file_checksum_frame,
    make_file_chunk_frame,
    make_file_upload_frame,
)
from .protocol import ErrorCode, Opcode, ProtocolError


def upload_file(sock: socket.socket, local_filepath: Path, remote_filename: str) -> None:
    """
    Thực hiện luồng Upload file từ Client lên Server.
    
    1. Kiểm tra file tồn tại.
    2. Gửi FILE_UPLOAD mang metadata (tên file, tổng kích thước).
    3. Nhận ACK từ Server xác nhận sẵn sàng.
    4. Đọc từng chunk 32KB -> gửi FILE_CHUNK -> tính SHA-256.
    5. Gửi FILE_CHECKSUM mang sha256_digest vừa tính.
    6. Nhận ACK cuối cùng từ Server xác nhận thành công.
    """
    path = Path(local_filepath)
    if not path.is_file():
        raise FileNotFoundError(f"File không tồn tại: {local_filepath}")

    total_size = path.stat().st_size

    # --- BƯỚC 1: Gửi FILE_UPLOAD mở đầu ---
    upload_msg = FileUpload(filename=remote_filename, total_size=total_size, start_offset=0)
    send_frame(sock, make_file_upload_frame(upload_msg))

    # Chờ Server ACK xác nhận đồng ý nhận file
    response_frame = receive_frame(sock)
    if response_frame is None:
        raise ConnectionError("Server đã đóng kết nối trước khi phản hồi FILE_UPLOAD")

    response_msg = decode_message(response_frame)
    if isinstance(response_msg, ErrorMessage):
        raise ProtocolError(response_msg.error_code, f"Server từ chối Upload: {response_msg.message}")
    if not isinstance(response_msg, Acknowledgement) or response_msg.acknowledged_opcode != Opcode.FILE_UPLOAD:
        raise ProtocolError(ErrorCode.INVALID_FRAME, "Kỳ vọng ACK cho FILE_UPLOAD từ Server")

    # --- BƯỚC 2: Truyền từng FILE_CHUNK & tính SHA-256 ---
    chunk_generator = read_file_chunks(path)
    final_offset = 0
    computed_digest = b""

    try:
        while True:
            # Lấy chunk tiếp theo từ generator
            chunk_msg, _ = next(chunk_generator)
            send_frame(sock, make_file_chunk_frame(chunk_msg))
    except StopIteration as return_value:
        # Generator kết thúc và trả về (total_bytes, sha256_digest)
        final_offset, computed_digest = return_value.value

    # --- BƯỚC 3: Gửi FILE_CHECKSUM ---
    checksum_msg = FileChecksum(final_size=final_offset, sha256_digest=computed_digest)
    send_frame(sock, make_file_checksum_frame(checksum_msg))

    # Chờ ACK cuối cùng xác nhận Checksum khớp
    final_frame = receive_frame(sock)
    if final_frame is None:
        raise ConnectionError("Server đóng kết nối trước khi xác nhận Checksum")

    final_resp = decode_message(final_frame)
    if isinstance(final_resp, ErrorMessage):
        raise ProtocolError(final_resp.error_code, f"Upload thất bại tại Server: {final_resp.message}")
    if not isinstance(final_resp, Acknowledgement) or final_resp.acknowledged_opcode != Opcode.FILE_CHECKSUM:
        raise ProtocolError(ErrorCode.INVALID_FRAME, "Kỳ vọng ACK cho FILE_CHECKSUM từ Server")

    print(f"[Client] Upload hoàn tất thành công: {remote_filename} ({final_offset} bytes)")