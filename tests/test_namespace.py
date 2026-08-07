"""Tests for Branch 3: feat/phase2-namespace per-user storage isolation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import socket

import pytest

from hcmus_socket.config import AppConfig, ServerConfig
from hcmus_socket.framing import (
    encode_preface,
    receive_frame,
    recv_exact,
    send_all,
    send_frame,
)
from hcmus_socket.messages import (
    Acknowledgement,
    FileChecksum,
    FileChunk,
    FileDownload,
    FileUpload,
    LoginRequest,
    make_acknowledgement_frame,
    make_disconnect_frame,
    make_file_checksum_frame,
    make_file_chunk_frame,
    make_file_download_frame,
    make_file_list_frame,
    make_file_upload_frame,
    make_login_frame,
    parse_acknowledgement,
    parse_error,
    parse_file_checksum,
    parse_file_chunk,
    parse_file_info,
    parse_file_list_response,
)
from hcmus_socket.protocol import ErrorCode, Opcode, ProtocolError
from hcmus_socket.server.registry import ActiveSessionRegistry
from hcmus_socket.server.namespace import (
    ensure_user_namespace,
    is_internal_file,
    resolve_namespace_path,
)
from hcmus_socket.server.session import ServerSession


def make_config(storage: Path) -> AppConfig:
    return AppConfig(server=ServerConfig(storage_directory=storage))


def start_session(
    executor: ThreadPoolExecutor,
    config: AppConfig,
    registry: ActiveSessionRegistry,
) -> tuple[ServerSession, socket.socket, object]:
    server_socket, client = socket.socketpair()
    client.settimeout(2)
    session = ServerSession(
        server_socket,
        ("local", 0),
        config,
        registry=registry,
    )
    future = executor.submit(session.run)
    return session, client, future


def exchange_preface(client: socket.socket) -> None:
    send_all(client, encode_preface())
    assert recv_exact(client, 8) == encode_preface()


def login(client: socket.socket, username: str) -> int:
    exchange_preface(client)
    send_frame(client, make_login_frame(LoginRequest(username)))
    response = receive_frame(client)
    assert response is not None
    ack = parse_acknowledgement(response)
    assert ack.acknowledged_opcode is Opcode.LOGIN
    return response.user_id


def upload_file(client: socket.socket, user_id: int, filename: str, content: bytes) -> None:
    send_frame(
        client,
        make_file_upload_frame(FileUpload(filename, len(content)), user_id=user_id),
    )
    ack1 = receive_frame(client)
    assert ack1 is not None
    assert parse_acknowledgement(ack1).acknowledged_opcode is Opcode.FILE_UPLOAD

    digest = hashlib.sha256(content).digest()
    send_frame(
        client,
        make_file_chunk_frame(FileChunk(0, content), user_id=user_id),
    )
    send_frame(
        client,
        make_file_checksum_frame(FileChecksum(len(content), digest), user_id=user_id),
    )
    ack2 = receive_frame(client)
    assert ack2 is not None
    assert parse_acknowledgement(ack2).acknowledged_opcode is Opcode.FILE_CHECKSUM


def download_file(client: socket.socket, user_id: int, filename: str) -> bytes:
    send_frame(
        client,
        make_file_download_frame(FileDownload(filename), user_id=user_id),
    )
    info_frame = receive_frame(client)
    assert info_frame is not None
    info = parse_file_info(info_frame)

    send_frame(
        client,
        make_acknowledgement_frame(
            Acknowledgement(Opcode.FILE_INFO, 0),
            user_id=user_id,
        ),
    )

    chunk_frame = receive_frame(client)
    assert chunk_frame is not None
    chunk = parse_file_chunk(chunk_frame)

    checksum_frame = receive_frame(client)
    assert checksum_frame is not None
    checksum = parse_file_checksum(checksum_frame)

    send_frame(
        client,
        make_acknowledgement_frame(
            Acknowledgement(Opcode.FILE_CHECKSUM, len(chunk.data)),
            user_id=user_id,
        ),
    )
    return chunk.data


def disconnect(client: socket.socket, user_id: int) -> None:
    send_frame(client, make_disconnect_frame(user_id=user_id))
    resp = receive_frame(client)
    assert resp is not None
    assert parse_acknowledgement(resp).acknowledged_opcode is Opcode.DISCONNECT


def test_alice_and_bob_upload_same_filename_with_different_content(tmp_path: Path) -> None:
    registry = ActiveSessionRegistry()
    config = make_config(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        _s1, client_alice, f1 = start_session(executor, config, registry)
        _s2, client_bob, f2 = start_session(executor, config, registry)

        alice_id = login(client_alice, "alice")
        bob_id = login(client_bob, "bob")

        upload_file(client_alice, alice_id, "data.bin", b"alice payload")
        upload_file(client_bob, bob_id, "data.bin", b"bob different payload")

        assert (tmp_path / "alice" / "data.bin").read_bytes() == b"alice payload"
        assert (tmp_path / "bob" / "data.bin").read_bytes() == b"bob different payload"

        disconnect(client_alice, alice_id)
        disconnect(client_bob, bob_id)
        f1.result(timeout=2)
        f2.result(timeout=2)
        client_alice.close()
        client_bob.close()


def test_alice_only_lists_alice_files_and_bob_only_downloads_bob_files(tmp_path: Path) -> None:
    registry = ActiveSessionRegistry()
    config = make_config(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        _s1, client_alice, f1 = start_session(executor, config, registry)
        _s2, client_bob, f2 = start_session(executor, config, registry)

        alice_id = login(client_alice, "alice")
        bob_id = login(client_bob, "bob")

        upload_file(client_alice, alice_id, "alice.txt", b"alice content")
        upload_file(client_bob, bob_id, "bob.txt", b"bob content")

        send_frame(client_alice, make_file_list_frame(user_id=alice_id))
        alice_list_resp = receive_frame(client_alice)
        assert alice_list_resp is not None
        alice_entries = parse_file_list_response(alice_list_resp).entries
        assert [e.filename for e in alice_entries] == ["alice.txt"]

        bob_download = download_file(client_bob, bob_id, "bob.txt")
        assert bob_download == b"bob content"

        # Bob attempts to download alice's file -> FILE_NOT_FOUND
        send_frame(client_bob, make_file_download_frame(FileDownload("alice.txt"), user_id=bob_id))
        bob_err = receive_frame(client_bob)
        assert bob_err is not None
        err = parse_error(bob_err)
        assert err.error_code is ErrorCode.FILE_NOT_FOUND

        disconnect(client_alice, alice_id)
        disconnect(client_bob, bob_id)
        f1.result(timeout=2)
        f2.result(timeout=2)
        client_alice.close()
        client_bob.close()


def test_cannot_access_traversal_path_or_escape_namespace(tmp_path: Path) -> None:
    alice_dir = ensure_user_namespace(tmp_path, "alice")
    bob_dir = ensure_user_namespace(tmp_path, "bob")
    (bob_dir / "secret.txt").write_bytes(b"secret")

    with pytest.raises(ProtocolError) as exc_info:
        resolve_namespace_path(alice_dir, "../bob/secret.txt")
    assert exc_info.value.code in {ErrorCode.INVALID_FILENAME, ErrorCode.ACCESS_DENIED}


def test_part_files_and_part_meta_not_in_list(tmp_path: Path) -> None:
    registry = ActiveSessionRegistry()
    config = make_config(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        _s, client, f = start_session(executor, config, registry)
        user_id = login(client, "alice")

        upload_file(client, user_id, "done.txt", b"done")
        alice_dir = tmp_path / "alice"
        (alice_dir / "temp.bin.part").write_bytes(b"partial")
        (alice_dir / "temp.bin.part.meta").write_bytes(b"meta")

        send_frame(client, make_file_list_frame(user_id=user_id))
        resp = receive_frame(client)
        assert resp is not None
        entries = parse_file_list_response(resp).entries
        assert [e.filename for e in entries] == ["done.txt"]

        disconnect(client, user_id)
        f.result(timeout=2)
        client.close()


def test_login_again_accesses_existing_namespace_other_user_cannot_access(tmp_path: Path) -> None:
    registry = ActiveSessionRegistry()
    config = make_config(tmp_path)

    # First session: Alice uploads a file
    with ThreadPoolExecutor(max_workers=1) as executor:
        _s, client, f = start_session(executor, config, registry)
        user_id = login(client, "alice")
        upload_file(client, user_id, "persistent.txt", b"data")
        disconnect(client, user_id)
        f.result(timeout=2)
        client.close()

    # Second session: Alice logs in again, file persists
    with ThreadPoolExecutor(max_workers=1) as executor:
        _s, client, f = start_session(executor, config, registry)
        user_id = login(client, "alice")
        data = download_file(client, user_id, "persistent.txt")
        assert data == b"data"
        disconnect(client, user_id)
        f.result(timeout=2)
        client.close()

    # Third session: Bob logs in, cannot see Alice's persistent.txt
    with ThreadPoolExecutor(max_workers=1) as executor:
        _s, client, f = start_session(executor, config, registry)
        user_id = login(client, "bob")
        send_frame(client, make_file_list_frame(user_id=user_id))
        resp = receive_frame(client)
        assert resp is not None
        entries = parse_file_list_response(resp).entries
        assert entries == ()
        disconnect(client, user_id)
        f.result(timeout=2)
        client.close()
