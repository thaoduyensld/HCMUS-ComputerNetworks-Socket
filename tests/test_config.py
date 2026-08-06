from __future__ import annotations

from pathlib import Path

import pytest

from hcmus_socket.config import AppConfig, AuthConfig, ConfigError, load_config


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "app.ini"
    path.write_text(content, encoding="utf-8")
    return path


def assert_config_error(tmp_path: Path, content: str, expected: str) -> None:
    path = write_config(tmp_path, content)

    with pytest.raises(ConfigError) as raised:
        load_config(path)

    message = str(raised.value)
    assert str(path) in message
    assert expected in message


def test_loads_example_config() -> None:
    config = load_config(Path("config/app.example.ini"))

    assert config == AppConfig()
    assert config.server.max_clients == 10
    assert config.server.partial_ttl_seconds == 86400
    assert config.network.bandwidth_limit_kib_per_second == 500
    assert config.auth == AuthConfig(max_username_bytes=32)


def test_empty_file_uses_defaults(tmp_path: Path) -> None:
    assert load_config(write_config(tmp_path, "")) == AppConfig()


def test_partial_config_preserves_missing_defaults(tmp_path: Path) -> None:
    config = load_config(
        write_config(
            tmp_path,
            """
[server]
port = 6000

[client]
connect_timeout_ms = 250
""",
        )
    )

    assert config.server.port == 6000
    assert config.server.bind_address == "0.0.0.0"
    assert config.client.connect_timeout_ms == 250
    assert config.network == AppConfig().network
    assert config.auth == AppConfig().auth


def test_loads_phase_two_config_boundaries(tmp_path: Path) -> None:
    config = load_config(
        write_config(
            tmp_path,
            """
[server]
max_clients = 1
partial_ttl_seconds = 0

[network]
bandwidth_limit_kib_per_second = 0

[auth]
max_username_bytes = 1
""",
        )
    )

    assert config.server.max_clients == 1
    assert config.server.partial_ttl_seconds == 0
    assert config.network.bandwidth_limit_kib_per_second == 0
    assert config.auth.max_username_bytes == 1


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("[unknown]\n", "unknown"),
        ("[server]\nunknown = value\n", "unknown"),
        ("[server]\nport = 1\nport = 2\n", "port"),
        ("port = 4567\n", "syntax"),
        ("[server\nport = 4567\n", "syntax"),
        ("[server]\nbind_address = 127.0.0.1\n  continued\n", "bind_address"),
    ],
)
def test_rejects_invalid_ini_structure(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    assert_config_error(tmp_path, content, expected)


@pytest.mark.parametrize("value", ["abc", "1.5", "-1", "+1"])
def test_rejects_invalid_integer(tmp_path: Path, value: str) -> None:
    assert_config_error(tmp_path, f"[server]\nport = {value}\n", "port")


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("server", "port", 0),
        ("server", "port", 65536),
        ("client", "server_port", 0),
        ("client", "server_port", 65536),
        ("client", "connect_timeout_ms", 0),
        ("client", "connect_timeout_ms", 300001),
        ("network", "chunk_size_bytes", 4095),
        ("network", "chunk_size_bytes", 65537),
        ("network", "max_payload_bytes", 16 * 1024 * 1024 + 1),
        ("server", "max_clients", 0),
        ("server", "partial_ttl_seconds", -1),
        ("network", "bandwidth_limit_kib_per_second", -1),
        ("auth", "max_username_bytes", 0),
        ("auth", "max_username_bytes", 33),
    ],
)
def test_rejects_out_of_range_values(
    tmp_path: Path,
    section: str,
    key: str,
    value: int,
) -> None:
    assert_config_error(tmp_path, f"[{section}]\n{key} = {value}\n", key)


def test_rejects_payload_smaller_than_chunk_plus_offset(tmp_path: Path) -> None:
    assert_config_error(
        tmp_path,
        """
[network]
max_payload_bytes = 4096
chunk_size_bytes = 4096
""",
        "max_payload_bytes",
    )


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("server", "bind_address"),
        ("server", "storage_directory"),
        ("client", "server_address"),
        ("client", "download_directory"),
    ],
)
def test_rejects_empty_text_and_path_values(
    tmp_path: Path,
    section: str,
    key: str,
) -> None:
    assert_config_error(tmp_path, f"[{section}]\n{key} = \n", key)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "missing.ini"

    with pytest.raises(ConfigError) as raised:
        load_config(path)

    assert str(path) in str(raised.value)
    assert "read" in str(raised.value)


def test_comments_and_blank_lines_are_supported(tmp_path: Path) -> None:
    config = load_config(
        write_config(
            tmp_path,
            """
# leading comment

[server]
; section comment
port = 1234

""",
        )
    )

    assert config.server.port == 1234


def test_interpolation_is_disabled(tmp_path: Path) -> None:
    config = load_config(
        write_config(tmp_path, "[server]\nbind_address = %(HOST_ADDRESS)s\n")
    )

    assert config.server.bind_address == "%(HOST_ADDRESS)s"


def test_relative_paths_remain_relative_and_are_not_created(tmp_path: Path) -> None:
    relative = Path("nested/storage")
    config = load_config(
        write_config(
            tmp_path,
            f"[server]\nstorage_directory = {relative.as_posix()}\n",
        )
    )

    assert config.server.storage_directory == relative
    assert not config.server.storage_directory.is_absolute()
    assert not (tmp_path / relative).exists()
