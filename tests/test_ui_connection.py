from __future__ import annotations

from hcmus_socket.client.session import AuthenticationError, SessionError
from hcmus_socket.config import AppConfig, ClientConfig
from hcmus_socket.protocol import ErrorCode, ProtocolError
from hcmus_socket.ui.app import (
    DOWNLOAD_TASK,
    UPLOAD_TASK,
    connection_config,
    connection_error_message,
    transfer_task_name,
    validate_download_destination,
    validate_upload_source,
)


def test_connection_config_replaces_only_server_endpoint() -> None:
    base = AppConfig(
        client=ClientConfig(
            server_address="old.example",
            server_port=1111,
            connect_timeout_ms=9000,
        )
    )

    configured = connection_config(base, "192.0.2.10", 4567)

    assert configured.client.server_address == "192.0.2.10"
    assert configured.client.server_port == 4567
    assert configured.client.connect_timeout_ms == 9000
    assert base.client.server_address == "old.example"
    assert configured.server is base.server
    assert configured.network is base.network


def test_connection_error_message_preserves_expected_client_errors() -> None:
    authentication = AuthenticationError(ErrorCode.USERNAME_IN_USE, "already active")
    session = SessionError("connection closed")

    assert connection_error_message(authentication) == (
        "That username is already connected. Choose another username."
    )
    assert connection_error_message(session) == "connection closed"
    assert connection_error_message(TimeoutError("timed out")) == "timed out"


def test_connection_error_message_labels_unexpected_failure() -> None:
    assert connection_error_message(ValueError("bad state")) == "unexpected error: bad state"
    assert connection_error_message(None) == "unknown connection error"


def test_transfer_action_maps_to_cancellable_worker_task() -> None:
    assert transfer_task_name("Upload") == UPLOAD_TASK
    assert transfer_task_name("Download") == DOWNLOAD_TASK
    assert transfer_task_name("Refresh") is None


def test_upload_source_validation_rejects_missing_path(tmp_path) -> None:
    missing = tmp_path / "missing.bin"

    assert validate_upload_source(missing) == (
        "The selected file no longer exists. Choose it again."
    )

    source = tmp_path / "data.bin"
    source.write_bytes(b"data")
    assert validate_upload_source(source) is None


def test_download_destination_validation_prevents_local_overwrite(tmp_path) -> None:
    existing = tmp_path / "existing.bin"
    existing.write_bytes(b"keep")

    assert validate_download_destination(existing) == (
        "A file or folder already exists at that location. Choose a new name."
    )
    assert validate_download_destination(tmp_path / "new.bin") is None


def test_phase2_errors_have_actionable_ui_messages() -> None:
    assert "10 active clients" in connection_error_message(
        ProtocolError(ErrorCode.SERVER_BUSY, "busy")
    )
    assert "incomplete result was not published" in connection_error_message(
        ProtocolError(ErrorCode.CHECKSUM_MISMATCH, "bad digest")
    )
