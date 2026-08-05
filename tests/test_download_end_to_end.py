from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket

from hcmus_socket.client.download import download_file
from hcmus_socket.config import AppConfig, ClientConfig, NetworkConfig, ServerConfig
from hcmus_socket.framing import receive_frame, send_frame
from hcmus_socket.messages import parse_file_download
from hcmus_socket.protocol import Frame
from hcmus_socket.server.download import handle_download


class FramedPeer:
    def __init__(self, sock: socket.socket, config: AppConfig) -> None:
        self.socket = sock
        self.config = config

    def send(self, frame: Frame) -> None:
        send_frame(
            self.socket,
            frame,
            max_payload_bytes=self.config.network.max_payload_bytes,
        )

    def receive(self) -> Frame:
        frame = receive_frame(
            self.socket,
            max_payload_bytes=self.config.network.max_payload_bytes,
        )
        if frame is None:
            raise ConnectionError("peer disconnected")
        return frame


def test_client_and_server_download_over_real_socket(tmp_path: Path) -> None:
    storage = tmp_path / "server"
    downloads = tmp_path / "client"
    storage.mkdir()
    data = bytes(range(256)) * 100
    (storage / "binary.bin").write_bytes(data)
    config = AppConfig(
        server=ServerConfig(storage_directory=storage),
        client=ClientConfig(download_directory=downloads),
        network=NetworkConfig(max_payload_bytes=65536, chunk_size_bytes=4096),
    )
    client_socket, server_socket = socket.socketpair()
    client = FramedPeer(client_socket, config)
    server = FramedPeer(server_socket, config)

    def serve_download() -> object:
        request = parse_file_download(server.receive(), config.network.max_payload_bytes)
        return handle_download(server, request)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            server_result_future = executor.submit(serve_download)
            client_result = download_file(client, "binary.bin")  # type: ignore[arg-type]
            server_result = server_result_future.result(timeout=5)
    finally:
        client_socket.close()
        server_socket.close()

    assert client_result.path.read_bytes() == data
    assert client_result.bytes_received == len(data)
    assert server_result.success  # type: ignore[attr-defined]
    assert server_result.bytes_sent == len(data)  # type: ignore[attr-defined]
