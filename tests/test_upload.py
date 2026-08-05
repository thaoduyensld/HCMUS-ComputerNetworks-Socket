import socket
import threading
from pathlib import Path
from hcmus_socket.client_upload import upload_file
from hcmus_socket.server_upload import handle_server_upload
from hcmus_socket.framing import receive_frame
from hcmus_socket.messages import decode_message, FileUpload

def test_upload_streaming_success(tmp_path: Path):
    # 1. Tạo file nguồn giả lập (ví dụ: 100KB)
    source_file = tmp_path / "test_data.bin"
    dummy_data = b"HCMUS_SOCKET_PROTOCOL_TEST_" * 4000
    source_file.write_bytes(dummy_data)

    server_dir = tmp_path / "server_storage"
    
    # 2. Dựng cặp socket kết nối trực tiếp (socketpair)
    server_sock, client_sock = socket.socketpair()

    # Function giả lập Server nhận Upload
    def run_server():
        # Server đợi nhận khung FILE_UPLOAD đầu tiên
        frame = receive_frame(server_sock)
        assert frame is not None
        msg = decode_message(frame)
        assert isinstance(msg, FileUpload)
        
        # Bắt đầu luồng xử lý nhận upload
        handle_server_upload(server_sock, msg, server_dir)
        server_sock.close()

    server_thread = threading.Thread(target=run_server)
    server_thread.start()

    # 3. Client thực hiện upload
    upload_file(client_sock, source_file, "uploaded_test.bin")
    client_sock.close()
    server_thread.join()

    # 4. Kiểm tra kết quả
    uploaded_file = server_dir / "uploaded_test.bin"
    assert uploaded_file.exists()
    assert uploaded_file.read_bytes() == dummy_data
    assert not (server_dir / "uploaded_test.bin.part").exists()  # Đảm bảo đã dọn dẹp file .part 