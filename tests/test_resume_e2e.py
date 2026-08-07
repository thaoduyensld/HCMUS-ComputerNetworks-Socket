import hashlib
import os
from pathlib import Path
import pytest

# Lưu ý: Import các module Client/Server thực tế của dự án
# from hcmus_socket.client.upload import upload_file
# from hcmus_socket.client.download import download_file


def generate_dummy_file(filepath: Path, size_bytes: int) -> str:
    """Tạo file dummy nhị phân và trả về checksum SHA-256."""
    data = os.urandom(size_bytes)
    filepath.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("interrupt_ratio", [0.3, 0.5, 0.7])
def test_upload_resume_e2e(tmp_path, interrupt_ratio):
    """Test Upload ngắt kết nối dở dang và resume hoàn tất."""
    file_size = 100 * 1024 * 1024  # 100 MB test file
    src_file = tmp_path / "large_upload.bin"
    original_hash = generate_dummy_file(src_file, file_size)

    # 1. Giả lập Upload đứt kết nối ở ratio (30%, 50%, 70%)
    # - Bắt exception ngắt kết nối
    # - Kiểm tra file .part và .part.meta tồn tại trên Server storage

    # 2. Reconnect với cùng username và tiếp tục Upload
    # result = upload_file(session, src_file, "large_upload.bin")

    # 3. Assert kết quả SHA-256 khớp bản gốc
    # dest_file = server_storage / "username" / "large_upload.bin"
    # assert hashlib.sha256(dest_file.read_bytes()).hexdigest() == original_hash


@pytest.mark.parametrize("interrupt_ratio", [0.3, 0.5, 0.7])
def test_download_resume_e2e(tmp_path, interrupt_ratio):
    """Test Download ngắt kết nối dở dang và resume hoàn tất."""
    file_size = 100 * 1024 * 1024  # 100 MB test file
    server_file = tmp_path / "server_storage" / "user" / "large_download.bin"
    server_file.parent.mkdir(parents=True, exist_ok=True)
    original_hash = generate_dummy_file(server_file, file_size)

    # 1. Giả lập Download đứt kết nối giữa chừng
    # - Bắt exception ngắt kết nối
    # - Kiểm tra client giữ file .part cục bộ

    # 2. Reconnect và Download lại
    # result = download_file(session, "large_download.bin")

    # 3. Assert file tải về khớp SHA-256
    # client_file = tmp_path / "downloads" / "large_download.bin"
    # assert hashlib.sha256(client_file.read_bytes()).hexdigest() == original_hash 