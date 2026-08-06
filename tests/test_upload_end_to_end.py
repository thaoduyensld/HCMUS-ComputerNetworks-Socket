"""Integration end-to-end tests for upload flow."""

from __future__ import annotations

import socket
import threading
from pathlib import Path

from hcmus_socket.client.upload import upload_file
from hcmus_socket.config import AppConfig
from hcmus_socket.framing import receive_frame
from hcmus_socket.messages import FileUpload, decode_message
from hcmus_socket.server.session import ServerSession
from hcmus_socket.server.upload import handle_server_upload


def test_upload_streaming_end_to_end(tmp_path: Path) -> None:
    """Test truyền file hoàn chỉnh giữa Client và Server thực tế."""
    source_file = tmp_path / "test_data.bin"
    dummy_data = b"HCMUS_SOCKET_PROTOCOL_TEST_" * 2000
    source_file.write_bytes(dummy_data)

    server_dir = tmp_path / "server_storage"
    config = AppConfig()

    server_sock, client_sock = socket.socketpair()

    def run_server() -> None:
        # Giả lập ServerSession nhận request
        session = ServerSession(server_sock, ("127.0.0.1", 0), config)
        frame = session.receive()
        msg = decode_message(frame)
        assert isinstance(msg, FileUpload)

        handle_server_upload(session, msg, server_dir)
        server_sock.close()

    server_thread = threading.Thread(target=run_server)
    server_thread.start()

    # Giả lập ClientSession đơn giản
    class DummyClientSession:
        def __init__(self, sock: socket.socket) -> None:
            self.socket = sock
            self.config = config

        def send(self, frame) -> None:
            from hcmus_socket.framing import send_frame
            send_frame(self.socket, frame, max_payload_bytes=self.config.network.max_payload_bytes)

        def receive(self):
            from hcmus_socket.framing import receive_frame
            return receive_frame(self.socket, max_payload_bytes=self.config.network.max_payload_bytes)

    client_session = DummyClientSession(client_sock)
    upload_file(client_session, source_file, "uploaded_test.bin")

    client_sock.close()
    server_thread.join()

    # Kiểm tra kết quả sau khi upload
    uploaded_file = server_dir / "uploaded_test.bin"
    assert uploaded_file.exists()
    assert uploaded_file.read_bytes() == dummy_data
    assert not (server_dir / "uploaded_test.bin.part").exists() 