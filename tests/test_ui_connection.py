from __future__ import annotations

from hcmus_socket.client.session import AuthenticationError, SessionError
from hcmus_socket.config import AppConfig, ClientConfig
from hcmus_socket.protocol import ErrorCode
from hcmus_socket.ui.app import connection_config, connection_error_message


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

    assert connection_error_message(authentication) == "already active"
    assert connection_error_message(session) == "connection closed"
    assert connection_error_message(TimeoutError("timed out")) == "timed out"


def test_connection_error_message_labels_unexpected_failure() -> None:
    assert connection_error_message(ValueError("bad state")) == "unexpected error: bad state"
    assert connection_error_message(None) == "unknown connection error"
