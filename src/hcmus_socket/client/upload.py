"""Client upload logic for Phase 1."""

from __future__ import annotations

from pathlib import Path

from ..file_transfer import read_file_chunks
from ..messages import (
    Acknowledgement,
    ErrorMessage,
    FileChecksum,
    FileUpload,
    decode_message,
    make_file_checksum_frame,
    make_file_chunk_frame,
    make_file_upload_frame,
)
from ..protocol import ErrorCode, Opcode, ProtocolError
from .session import ClientSession, SessionError


def upload_file(session: ClientSession, local_filepath: Path, remote_filename: str) -> None:
    """
    Thực hiện luồng Upload file từ Client lên Server bằng ClientSession.
    """
    path = Path(local_filepath)
    if not path.is_file():
        raise FileNotFoundError(f"File không tồn tại: {local_filepath}")

    total_size = path.stat().st_size

    # --- BƯỚC 1: Gửi FILE_UPLOAD mở đầu ---
    upload_msg = FileUpload(filename=remote_filename, total_size=total_size, start_offset=0)
    session.send(make_file_upload_frame(upload_msg))

    # Chờ Server ACK xác nhận đồng ý nhận file
    response_frame = session.receive()  # session.receive() tự xử lý nhận frame an toàn

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
            chunk_msg, _ = next(chunk_generator)
            session.send(make_file_chunk_frame(chunk_msg))
    except StopIteration as return_value:
        final_offset, computed_digest = return_value.value

    # --- BƯỚC 3: Gửi FILE_CHECKSUM ---
    checksum_msg = FileChecksum(final_size=final_offset, sha256_digest=computed_digest)
    session.send(make_file_checksum_frame(checksum_msg))

    # Chờ ACK cuối cùng xác nhận Checksum khớp
    final_frame = session.receive()

    final_resp = decode_message(final_frame)
    if isinstance(final_resp, ErrorMessage):
        raise ProtocolError(final_resp.error_code, f"Upload thất bại tại Server: {final_resp.message}")
    if not isinstance(final_resp, Acknowledgement) or final_resp.acknowledged_opcode != Opcode.FILE_CHECKSUM:
        raise ProtocolError(ErrorCode.INVALID_FRAME, "Kỳ vọng ACK cho FILE_CHECKSUM từ Server")

    print(f"[Client] Upload hoàn tất thành công: {remote_filename} ({final_offset} bytes)") 