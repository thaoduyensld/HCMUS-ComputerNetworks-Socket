from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from hcmus_socket.config import AppConfig, ServerConfig
from hcmus_socket.protocol import ErrorCode, Opcode
from hcmus_socket.server.download import DownloadTransferResult
from hcmus_socket.server.logger import ServerLogger


FIXED_TIME = datetime(2026, 8, 6, 3, 4, 5, 678000, tzinfo=timezone.utc)


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_connection_and_disconnection_events_are_parseable(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    with ServerLogger(path, clock=lambda: FIXED_TIME) as logger:
        assert logger.log_connection(("127.0.0.1", 50000))
        assert logger.log_disconnection(
            ("127.0.0.1", 50000),
            clean=False,
            message="peer reset",
        )

    connected, disconnected = read_events(path)
    assert connected == {
        "client_ip": "127.0.0.1",
        "client_port": 50000,
        "error_code": None,
        "error_code_value": None,
        "event": "connection",
        "message": None,
        "result": "success",
        "timestamp": "2026-08-06T03:04:05.678+00:00",
    }
    assert disconnected["event"] == "disconnection"
    assert disconnected["result"] == "failure"
    assert disconnected["message"] == "peer reset"


def test_transfer_contains_all_required_fields_and_exact_speed(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    with ServerLogger(path, clock=lambda: FIXED_TIME) as logger:
        assert logger.log_transfer(
            ("192.0.2.1", 1234),
            Opcode.FILE_DOWNLOAD,
            filename='dữ liệu "01".bin',
            bytes_transferred=2048,
            duration_seconds=0.5,
            success=True,
            checksum_matched=True,
        )

    event = read_events(path)[0]
    assert event["timestamp"] == "2026-08-06T03:04:05.678+00:00"
    assert event["client_ip"] == "192.0.2.1"
    assert event["client_port"] == 1234
    assert event["command"] == "FILE_DOWNLOAD"
    assert event["filename"] == 'dữ liệu "01".bin'
    assert event["bytes"] == 2048
    assert event["duration_ms"] == 500.0
    assert event["speed_kib_s"] == 4.0
    assert event["result"] == "success"
    assert event["checksum"] == "match"
    assert event["error_code"] is None


def test_download_result_adapter_logs_failure(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    result = DownloadTransferResult(
        filename="missing.bin",
        bytes_sent=0,
        duration_seconds=0.01,
        success=False,
        checksum_matched=None,
        error_code=ErrorCode.FILE_NOT_FOUND,
    )
    with ServerLogger(path) as logger:
        assert logger.log_download(("203.0.113.2", 9000), result)

    event = read_events(path)[0]
    assert event["command"] == "FILE_DOWNLOAD"
    assert event["result"] == "failure"
    assert event["error_code"] == "FILE_NOT_FOUND"
    assert event["error_code_value"] == int(ErrorCode.FILE_NOT_FOUND)
    assert event["checksum"] == "n/a"


def test_list_command_can_be_logged_without_filename(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    with ServerLogger(path) as logger:
        logger.log_transfer(
            ("127.0.0.1", 1),
            "list",
            filename=None,
            bytes_transferred=0,
            duration_seconds=0,
            success=True,
        )

    event = read_events(path)[0]
    assert event["command"] == "LIST"
    assert event["filename"] is None
    assert event["speed_kib_s"] == 0.0


def test_concurrent_writes_remain_complete_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    count = 100
    with ServerLogger(path) as logger:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(
                    lambda index: logger.log_transfer(
                        ("127.0.0.1", 1000 + index),
                        Opcode.FILE_DOWNLOAD,
                        filename=f"file-{index}.bin",
                        bytes_transferred=index,
                        duration_seconds=0.01,
                        success=True,
                        checksum_matched=True,
                    ),
                    range(count),
                )
            )

    events = read_events(path)
    assert all(results)
    assert len(events) == count
    assert {event["filename"] for event in events} == {
        f"file-{index}.bin" for index in range(count)
    }


def test_runtime_log_failure_does_not_raise(tmp_path: Path) -> None:
    logger = ServerLogger(tmp_path / "server.log")
    logger.close()

    assert not logger.log_connection(("127.0.0.1", 1234))
    assert isinstance(logger.last_error, OSError)


def test_from_config_places_log_inside_storage(tmp_path: Path) -> None:
    config = AppConfig(server=ServerConfig(storage_directory=tmp_path / "storage"))
    logger = ServerLogger.from_config(config)
    try:
        logger.log_connection(("127.0.0.1", 1234))
    finally:
        logger.close()

    assert logger.path == tmp_path / "storage" / "server.log"
    assert logger.path.is_file()


@pytest.mark.parametrize(
    ("bytes_transferred", "duration_seconds"),
    [(-1, 1.0), (1, -1.0)],
)
def test_negative_metrics_are_rejected(
    tmp_path: Path,
    bytes_transferred: int,
    duration_seconds: float,
) -> None:
    with ServerLogger(tmp_path / "server.log") as logger:
        with pytest.raises(ValueError):
            logger.log_transfer(
                ("127.0.0.1", 1),
                Opcode.FILE_DOWNLOAD,
                filename="data.bin",
                bytes_transferred=bytes_transferred,
                duration_seconds=duration_seconds,
                success=False,
            )
