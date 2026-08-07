from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
from threading import Event, enumerate as enumerate_threads

from hcmus_socket.config import AppConfig, NetworkConfig, ServerConfig
from hcmus_socket.framing import (
    encode_preface,
    receive_frame,
    recv_exact,
    send_all,
    send_frame,
)
from hcmus_socket.messages import (
    make_disconnect_frame,
    make_file_list_frame,
    parse_acknowledgement,
    parse_file_list_response,
)
from hcmus_socket.protocol import Opcode
from hcmus_socket.server.app import serve_forever


class CoordinatedListener:
    """Stop the test server after a fixed number of accepted connections."""

    def __init__(self, listener: socket.socket, limit: int, release: Event) -> None:
        self.listener = listener
        self.limit = limit
        self.release = release
        self.accepted = 0

    def accept(self) -> tuple[socket.socket, object]:
        if self.accepted == self.limit:
            if not self.release.wait(timeout=5):
                raise TimeoutError("test clients did not complete in time")
            raise KeyboardInterrupt
        connection = self.listener.accept()
        self.accepted += 1
        return connection

    def close(self) -> None:
        self.listener.close()


def test_server_serves_ten_clients_concurrently(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "shared.bin").write_bytes(b"shared")
    config = AppConfig(
        server=ServerConfig(
            bind_address="127.0.0.1",
            port=4567,
            storage_directory=storage,
        ),
        network=NetworkConfig(max_payload_bytes=65536, chunk_size_bytes=4096),
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(10)
    address = listener.getsockname()
    release = Event()
    coordinated = CoordinatedListener(listener, 10, release)
    clients: list[socket.socket] = []

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            server = executor.submit(
                serve_forever,
                config,
                listener=coordinated,  # type: ignore[arg-type]
            )
            clients = [
                socket.create_connection(address, timeout=2)
                for _ in range(10)
            ]
            for client in clients:
                client.settimeout(2)
                send_all(client, encode_preface())
            for client in clients:
                assert recv_exact(client, 8) == encode_preface()

            for client in clients:
                send_frame(client, make_file_list_frame())
            for client in clients:
                listing = parse_file_list_response(
                    receive_frame(client)  # type: ignore[arg-type]
                )
                assert [
                    (entry.filename, entry.file_size)
                    for entry in listing.entries
                ] == [("shared.bin", 6)]

            for client in clients:
                send_frame(client, make_disconnect_frame())
            for client in clients:
                acknowledgement = parse_acknowledgement(
                    receive_frame(client)  # type: ignore[arg-type]
                )
                assert acknowledgement.acknowledged_opcode is Opcode.DISCONNECT
                client.close()
            clients.clear()
            release.set()
            server.result(timeout=5)
    finally:
        release.set()
        for client in clients:
            client.close()

    assert coordinated.accepted == 10
    assert not any(
        thread.name.startswith("hcmus-client-")
        for thread in enumerate_threads()
    )
