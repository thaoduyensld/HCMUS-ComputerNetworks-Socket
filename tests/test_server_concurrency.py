from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
from threading import Event, enumerate as enumerate_threads
from time import monotonic, sleep

from hcmus_socket.config import AppConfig, NetworkConfig, ServerConfig
from hcmus_socket.framing import (
    encode_preface,
    receive_frame,
    recv_exact,
    send_all,
    send_frame,
)
from hcmus_socket.messages import (
    LoginRequest,
    make_disconnect_frame,
    make_file_list_frame,
    make_login_frame,
    parse_acknowledgement,
    parse_error,
    parse_file_list_response,
)
from hcmus_socket.protocol import ErrorCode, Opcode
from hcmus_socket.server.app import serve_forever
from hcmus_socket.server.registry import ActiveSessionRegistry


def authenticate(client: socket.socket, username: str) -> int:
    send_frame(client, make_login_frame(LoginRequest(username)))
    response = receive_frame(client)
    assert response is not None
    parse_acknowledgement(response)
    return response.user_id


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
    registry = ActiveSessionRegistry()
    clients: list[socket.socket] = []

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            server = executor.submit(
                serve_forever,
                config,
                listener=coordinated,  # type: ignore[arg-type]
                registry=registry,
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
            user_ids = []
            for index, client in enumerate(clients):
                username = f"client{index}"
                namespace = storage / username
                namespace.mkdir()
                (namespace / "shared.bin").write_bytes(b"shared")
                user_ids.append(authenticate(client, username))
            deadline = monotonic() + 2
            while registry.active_count != 10:
                if monotonic() >= deadline:
                    raise AssertionError("sessions were not registered")
                sleep(0.01)

            for client, user_id in zip(clients, user_ids, strict=True):
                send_frame(client, make_file_list_frame(user_id=user_id))
            for client in clients:
                listing = parse_file_list_response(
                    receive_frame(client)  # type: ignore[arg-type]
                )
                assert [
                    (entry.filename, entry.file_size)
                    for entry in listing.entries
                ] == [("shared.bin", 6)]

            for client, user_id in zip(clients, user_ids, strict=True):
                send_frame(client, make_disconnect_frame(user_id=user_id))
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
    assert registry.active_count == 0
    assert not any(
        thread.name.startswith("hcmus-client-")
        for thread in enumerate_threads()
    )
    events = [
        json.loads(line)
        for line in (storage / "server.log").read_text(encoding="utf-8").splitlines()
    ]
    assert len(events) == 40
    assert sum(event["event"] == "connection" for event in events) == 10
    assert sum(event["event"] == "disconnection" for event in events) == 10
    assert sum(event["event"] == "command" for event in events) == 20


def test_eleventh_client_receives_server_busy(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    config = AppConfig(
        server=ServerConfig(
            bind_address="127.0.0.1",
            port=4567,
            storage_directory=storage,
            max_clients=10,
        )
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(12)
    address = listener.getsockname()
    release = Event()
    coordinated = CoordinatedListener(listener, 12, release)
    admitted: list[socket.socket] = []
    extra: socket.socket | None = None
    replacement: socket.socket | None = None

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            server = executor.submit(
                serve_forever,
                config,
                listener=coordinated,  # type: ignore[arg-type]
            )
            admitted = [
                socket.create_connection(address, timeout=2)
                for _ in range(10)
            ]
            for client in admitted:
                client.settimeout(2)
                send_all(client, encode_preface())
            for client in admitted:
                assert recv_exact(client, 8) == encode_preface()
            admitted_user_ids = [
                authenticate(client, f"client{index}")
                for index, client in enumerate(admitted)
            ]

            extra = socket.create_connection(address, timeout=2)
            extra.settimeout(2)
            send_all(extra, encode_preface())
            assert recv_exact(extra, 8) == encode_preface()
            # The real ClientSession sends LOGIN immediately after receiving
            # the preface. The busy response must survive those unread bytes,
            # especially on Windows where a direct close can emit TCP RST.
            send_frame(extra, make_login_frame(LoginRequest("overflow")))
            response = receive_frame(extra)
            assert response is not None
            error = parse_error(response)
            assert error.failed_opcode == 0
            assert error.error_code is ErrorCode.SERVER_BUSY
            assert extra.recv(1) == b""
            extra.close()
            extra = None

            first = admitted.pop()
            first_user_id = admitted_user_ids.pop()
            send_frame(first, make_disconnect_frame(user_id=first_user_id))
            receive_frame(first)
            first.close()
            deadline = monotonic() + 2
            while sum(
                thread.name.startswith("hcmus-client-")
                for thread in enumerate_threads()
            ) >= 10:
                if monotonic() >= deadline:
                    raise AssertionError("released client slot was not returned")
                sleep(0.01)

            replacement = socket.create_connection(address, timeout=2)
            replacement.settimeout(2)
            send_all(replacement, encode_preface())
            assert recv_exact(replacement, 8) == encode_preface()
            replacement_user_id = authenticate(replacement, "replacement")

            for client, user_id in zip(admitted, admitted_user_ids, strict=True):
                send_frame(client, make_disconnect_frame(user_id=user_id))
            send_frame(replacement, make_disconnect_frame(user_id=replacement_user_id))
            for client in admitted:
                receive_frame(client)
                client.close()
            admitted.clear()
            receive_frame(replacement)
            replacement.close()
            replacement = None
            release.set()
            server.result(timeout=5)
    finally:
        release.set()
        if extra is not None:
            extra.close()
        if replacement is not None:
            replacement.close()
        for client in admitted:
            client.close()

    assert coordinated.accepted == 12


def test_failed_handshake_is_removed_from_session_registry(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    config = AppConfig(server=ServerConfig(storage_directory=storage))
    registry = ActiveSessionRegistry()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    address = listener.getsockname()
    release = Event()
    coordinated = CoordinatedListener(listener, 1, release)

    with ThreadPoolExecutor(max_workers=1) as executor:
        server = executor.submit(
            serve_forever,
            config,
            listener=coordinated,  # type: ignore[arg-type]
            registry=registry,
        )
        client = socket.create_connection(address, timeout=2)
        client.settimeout(2)
        send_all(client, bytes(8))
        assert client.recv(1) == b""
        client.close()
        release.set()
        server.result(timeout=5)

    assert registry.active_count == 0
    assert registry.authenticated_count == 0


def test_one_hundred_connect_login_disconnect_cycles_do_not_leak(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    config = AppConfig(
        server=ServerConfig(storage_directory=storage),
        network=NetworkConfig(bandwidth_limit_kib_per_second=0),
    )
    registry = ActiveSessionRegistry()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(10)
    address = listener.getsockname()
    release = Event()
    coordinated = CoordinatedListener(listener, 100, release)
    assigned_user_ids: list[int] = []

    with ThreadPoolExecutor(max_workers=1) as executor:
        server = executor.submit(
            serve_forever,
            config,
            listener=coordinated,  # type: ignore[arg-type]
            registry=registry,
        )
        for index in range(100):
            client = socket.create_connection(address, timeout=2)
            client.settimeout(2)
            send_all(client, encode_preface())
            assert recv_exact(client, 8) == encode_preface()
            user_id = authenticate(client, f"cycle-{index}")
            assigned_user_ids.append(user_id)
            send_frame(client, make_disconnect_frame(user_id=user_id))
            response = receive_frame(client)
            assert response is not None
            assert parse_acknowledgement(response).acknowledged_opcode is Opcode.DISCONNECT
            client.close()

            deadline = monotonic() + 2
            while registry.active_count:
                if monotonic() >= deadline:
                    raise AssertionError("session registry entry was not released")
                sleep(0.001)

        release.set()
        server.result(timeout=5)

    assert set(assigned_user_ids) == {1}
    assert registry.active_count == 0
    assert registry.authenticated_count == 0
    assert not any(
        thread.name.startswith("hcmus-client-")
        for thread in enumerate_threads()
    )
