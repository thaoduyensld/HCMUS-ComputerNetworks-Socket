"""Thread-safe JSON Lines logging for server sessions and transfers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import TextIO

from ..config import AppConfig
from ..protocol import ErrorCode, Opcode
from .download import DownloadTransferResult
from .upload import UploadTransferResult


ClientAddress = tuple[str, int]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class LoggerStatus:
    """Atomic diagnostic snapshot for the shared server logger."""

    closed: bool
    successful_writes: int
    failed_writes: int
    last_error: OSError | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServerLogger:
    """Append parseable session/transfer events to one JSON object per line.

    Opening the log is fail-fast so deployment/configuration errors are visible
    at server startup. Runtime write failures are contained and reported via a
    ``False`` return value, preventing logging from crashing a client session.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream: TextIO | None = self.path.open(
            "a",
            encoding="utf-8",
            buffering=1,
        )
        self._clock = clock
        self._lock = Lock()
        self._last_error: OSError | None = None
        self._successful_writes = 0
        self._failed_writes = 0

    @classmethod
    def from_config(cls, config: AppConfig) -> ServerLogger:
        return cls(config.server.storage_directory / "server.log")

    def log_connection(
        self,
        client: ClientAddress,
        *,
        success: bool = True,
        error_code: ErrorCode | None = None,
        message: str | None = None,
    ) -> bool:
        """Log one accepted or rejected TCP connection."""

        ip, port = _client_fields(client)
        return self._write(
            {
                "timestamp": self._timestamp(),
                "event": "connection",
                "client_ip": ip,
                "client_port": port,
                "result": "success" if success else "failure",
                "error_code": _error_name(error_code),
                "error_code_value": int(error_code) if error_code is not None else None,
                "message": message,
            }
        )

    def log_disconnection(
        self,
        client: ClientAddress,
        *,
        clean: bool,
        message: str | None = None,
    ) -> bool:
        """Log normal DISCONNECT or an interrupted TCP session."""

        ip, port = _client_fields(client)
        return self._write(
            {
                "timestamp": self._timestamp(),
                "event": "disconnection",
                "client_ip": ip,
                "client_port": port,
                "result": "success" if clean else "failure",
                "error_code": None,
                "error_code_value": None,
                "message": message,
            }
        )

    def log_transfer(
        self,
        client: ClientAddress,
        command: Opcode | str,
        *,
        filename: str | None,
        bytes_transferred: int,
        duration_seconds: float,
        success: bool,
        error_code: ErrorCode | None = None,
        checksum_matched: bool | None = None,
        message: str | None = None,
    ) -> bool:
        """Log one LIST/UPLOAD/DOWNLOAD result with timing and throughput."""

        if bytes_transferred < 0:
            raise ValueError("bytes_transferred must not be negative")
        if duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative")
        ip, port = _client_fields(client)
        speed = (
            bytes_transferred / 1024 / duration_seconds
            if duration_seconds > 0
            else 0.0
        )
        return self._write(
            {
                "timestamp": self._timestamp(),
                "event": "command",
                "client_ip": ip,
                "client_port": port,
                "command": _command_name(command),
                "filename": filename,
                "bytes": bytes_transferred,
                "duration_ms": round(duration_seconds * 1000, 3),
                "speed_kib_s": round(speed, 3),
                "result": "success" if success else "failure",
                "error_code": _error_name(error_code),
                "error_code_value": int(error_code) if error_code is not None else None,
                "checksum": _checksum_text(checksum_matched),
                "message": message,
            }
        )

    def log_download(
        self,
        client: ClientAddress,
        result: DownloadTransferResult,
        *,
        message: str | None = None,
    ) -> bool:
        """Adapter for the structured result returned by ``handle_download``."""

        return self.log_transfer(
            client,
            Opcode.FILE_DOWNLOAD,
            filename=result.filename,
            bytes_transferred=result.bytes_sent,
            duration_seconds=result.duration_seconds,
            success=result.success,
            error_code=result.error_code,
            checksum_matched=result.checksum_matched,
            message=message,
        )

    def log_upload(
        self,
        client: ClientAddress,
        result: UploadTransferResult,
        *,
        message: str | None = None,
    ) -> bool:
        """Adapter for the structured result returned by ``handle_upload``."""

        return self.log_transfer(
            client,
            Opcode.FILE_UPLOAD,
            filename=result.filename,
            bytes_transferred=result.bytes_received,
            duration_seconds=result.duration_seconds,
            success=result.success,
            error_code=result.error_code,
            checksum_matched=result.checksum_matched,
            message=message,
        )

    def close(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
            if stream is not None:
                try:
                    stream.close()
                except OSError as error:
                    self._last_error = error

    @property
    def last_error(self) -> OSError | None:
        with self._lock:
            return self._last_error

    def status(self) -> LoggerStatus:
        """Return counters and close state under the same lock used by writers."""

        with self._lock:
            return LoggerStatus(
                closed=self._stream is None,
                successful_writes=self._successful_writes,
                failed_writes=self._failed_writes,
                last_error=self._last_error,
            )

    def __enter__(self) -> ServerLogger:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")

    def _write(self, event: dict[str, object]) -> bool:
        line = json.dumps(
            event,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._lock:
            if self._stream is None:
                self._last_error = OSError("server logger is closed")
                self._failed_writes += 1
                return False
            try:
                self._stream.write(line + "\n")
                self._stream.flush()
                self._successful_writes += 1
                return True
            except OSError as error:
                self._last_error = error
                self._failed_writes += 1
                return False


def _client_fields(client: ClientAddress) -> tuple[str, int]:
    ip, port = client
    if not isinstance(ip, str) or not ip:
        raise ValueError("client IP must be non-empty text")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("client port must be from 0 to 65535")
    return ip, port


def _command_name(command: Opcode | str) -> str:
    if isinstance(command, Opcode):
        return command.name
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be an Opcode or non-empty text")
    return command.strip().upper()


def _error_name(error_code: ErrorCode | None) -> str | None:
    return error_code.name if error_code is not None else None


def _checksum_text(matched: bool | None) -> str:
    if matched is None:
        return "n/a"
    return "match" if matched else "mismatch"
