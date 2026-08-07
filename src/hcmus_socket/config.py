"""Strict INI configuration loading for the client and server."""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path
import re

from .protocol import (
    CHUNK_OFFSET_SIZE_BYTES,
    CHUNK_SIZE_BYTES,
    MAX_CHUNK_SIZE_BYTES,
    MAX_PAYLOAD_BYTES,
    MIN_CHUNK_SIZE_BYTES,
)


MAX_CONFIG_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_BANDWIDTH_BYTES_PER_SECOND = 1024 * 1024 * 1024
MAX_BANDWIDTH_BURST_BYTES = MAX_CONFIG_PAYLOAD_BYTES

_SECTION_KEYS = {
    "server": {"bind_address", "port", "storage_directory", "max_clients"},
    "client": {
        "server_address",
        "server_port",
        "connect_timeout_ms",
        "download_directory",
    },
    "network": {
        "max_payload_bytes",
        "chunk_size_bytes",
        "bandwidth_limit_bytes_per_second",
        "bandwidth_burst_bytes",
    },
}
_DECIMAL_INTEGER = re.compile(r"[0-9]+\Z")


class ConfigError(Exception):
    """Raised when a configuration file cannot be read or validated."""


@dataclass(frozen=True, slots=True)
class ServerConfig:
    bind_address: str = "0.0.0.0"
    port: int = 4567
    storage_directory: Path = Path("runtime/server_storage")
    max_clients: int = 10


@dataclass(frozen=True, slots=True)
class ClientConfig:
    server_address: str = "127.0.0.1"
    server_port: int = 4567
    connect_timeout_ms: int = 5000
    download_directory: Path = Path("runtime/client_downloads")


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    max_payload_bytes: int = MAX_PAYLOAD_BYTES
    chunk_size_bytes: int = CHUNK_SIZE_BYTES
    bandwidth_limit_bytes_per_second: int = 0
    bandwidth_burst_bytes: int = 0

    @property
    def bandwidth_limited(self) -> bool:
        return self.bandwidth_limit_bytes_per_second > 0


@dataclass(frozen=True, slots=True)
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    client: ClientConfig = field(default_factory=ClientConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)


def load_config(path: str | Path) -> AppConfig:
    """Load a strict Phase 1 INI file without resolving paths or interpolation."""

    config_path = Path(path)
    parser = configparser.ConfigParser(
        interpolation=None,
        delimiters=("=",),
        comment_prefixes=("#", ";"),
        inline_comment_prefixes=None,
        strict=True,
        empty_lines_in_values=False,
        default_section="__hcmus_defaults_are_disabled__",
    )
    parser.optionxform = str

    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            parser.read_file(config_file, source=str(config_path))
    except OSError as error:
        raise ConfigError(f"{config_path}: cannot read config file: {error}") from error
    except UnicodeError as error:
        raise ConfigError(f"{config_path}: config file is not valid UTF-8") from error
    except configparser.Error as error:
        raise ConfigError(_format_parser_error(config_path, error)) from error

    _validate_schema(config_path, parser)
    defaults = AppConfig()

    server = ServerConfig(
        bind_address=_text_value(
            config_path,
            parser,
            "server",
            "bind_address",
            defaults.server.bind_address,
        ),
        port=_integer_value(
            config_path,
            parser,
            "server",
            "port",
            defaults.server.port,
            1,
            65535,
        ),
        storage_directory=Path(
            _text_value(
                config_path,
                parser,
                "server",
                "storage_directory",
                str(defaults.server.storage_directory),
            )
        ),
        max_clients=_integer_value(
            config_path,
            parser,
            "server",
            "max_clients",
            defaults.server.max_clients,
            1,
            1000,
        ),
    )
    client = ClientConfig(
        server_address=_text_value(
            config_path,
            parser,
            "client",
            "server_address",
            defaults.client.server_address,
        ),
        server_port=_integer_value(
            config_path,
            parser,
            "client",
            "server_port",
            defaults.client.server_port,
            1,
            65535,
        ),
        connect_timeout_ms=_integer_value(
            config_path,
            parser,
            "client",
            "connect_timeout_ms",
            defaults.client.connect_timeout_ms,
            1,
            300000,
        ),
        download_directory=Path(
            _text_value(
                config_path,
                parser,
                "client",
                "download_directory",
                str(defaults.client.download_directory),
            )
        ),
    )
    network = NetworkConfig(
        max_payload_bytes=_integer_value(
            config_path,
            parser,
            "network",
            "max_payload_bytes",
            defaults.network.max_payload_bytes,
            1,
            MAX_CONFIG_PAYLOAD_BYTES,
        ),
        chunk_size_bytes=_integer_value(
            config_path,
            parser,
            "network",
            "chunk_size_bytes",
            defaults.network.chunk_size_bytes,
            MIN_CHUNK_SIZE_BYTES,
            MAX_CHUNK_SIZE_BYTES,
        ),
        bandwidth_limit_bytes_per_second=_integer_value(
            config_path,
            parser,
            "network",
            "bandwidth_limit_bytes_per_second",
            defaults.network.bandwidth_limit_bytes_per_second,
            0,
            MAX_BANDWIDTH_BYTES_PER_SECOND,
        ),
        bandwidth_burst_bytes=_integer_value(
            config_path,
            parser,
            "network",
            "bandwidth_burst_bytes",
            defaults.network.bandwidth_burst_bytes,
            0,
            MAX_BANDWIDTH_BURST_BYTES,
        ),
    )
    if network.max_payload_bytes < network.chunk_size_bytes + CHUNK_OFFSET_SIZE_BYTES:
        _fail(
            config_path,
            "network",
            "max_payload_bytes",
            "must be at least network.chunk_size_bytes + 8",
        )
    if network.bandwidth_limit_bytes_per_second == 0:
        if network.bandwidth_burst_bytes != 0:
            _fail(
                config_path,
                "network",
                "bandwidth_burst_bytes",
                "must be 0 when bandwidth_limit_bytes_per_second is 0",
            )
    elif network.bandwidth_burst_bytes < network.chunk_size_bytes:
        _fail(
            config_path,
            "network",
            "bandwidth_burst_bytes",
            "must be at least network.chunk_size_bytes when bandwidth limiting is enabled",
        )

    return AppConfig(server, client, network)


def _validate_schema(
    path: Path,
    parser: configparser.ConfigParser,
) -> None:
    for section in parser.sections():
        if section not in _SECTION_KEYS:
            _fail(path, section, None, "unknown section")
        for key, value in parser.items(section, raw=True):
            if key not in _SECTION_KEYS[section]:
                _fail(path, section, key, "unknown key")
            if "\n" in value:
                _fail(path, section, key, "multiline values are not supported")


def _text_value(
    path: Path,
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: str,
) -> str:
    if not parser.has_option(section, key):
        return default
    value = parser.get(section, key, raw=True).strip()
    if not value:
        _fail(path, section, key, "value cannot be empty")
    return value


def _integer_value(
    path: Path,
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if not parser.has_option(section, key):
        return default
    text = _text_value(path, parser, section, key, str(default))
    if _DECIMAL_INTEGER.fullmatch(text) is None:
        _fail(path, section, key, "value must be a decimal integer")
    value = int(text)
    if not minimum <= value <= maximum:
        _fail(path, section, key, f"value must be from {minimum} to {maximum}")
    return value


def _format_parser_error(path: Path, error: configparser.Error) -> str:
    section = getattr(error, "section", None)
    key = getattr(error, "option", None)
    line_number = getattr(error, "lineno", None)
    location = str(path)
    if line_number is not None:
        location += f":{line_number}"
    context = ""
    if section:
        context += f" [{section}]"
    if key:
        context += f".{key}"
    return f"{location}:{context} invalid INI syntax: {error}"


def _fail(path: Path, section: str, key: str | None, reason: str) -> None:
    setting = f"[{section}]"
    if key is not None:
        setting += f".{key}"
    raise ConfigError(f"{path}: {setting}: {reason}")
