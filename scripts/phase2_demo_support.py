"""Shared local-server utilities for repeatable Phase 2 demo scripts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
from queue import Empty, Queue
import socket
from threading import Event, Thread
from time import monotonic, sleep
from typing import Any

from hcmus_socket.client.session import ClientSession
from hcmus_socket.config import AppConfig, ClientConfig, NetworkConfig, ServerConfig
from hcmus_socket.server.app import (
    ClientWorkerGroup,
    create_listener,
    reject_busy,
)
from hcmus_socket.server.filename_locks import FilenameLockRegistry
from hcmus_socket.server.logger import ServerLogger
from hcmus_socket.server.registry import ActiveSessionRegistry


class LocalPhaseTwoServer:
    """Run the production worker/capacity path on an ephemeral loopback port."""

    def __init__(
        self,
        work_directory: Path,
        *,
        max_clients: int,
        bandwidth_limit_kib_per_second: int,
    ) -> None:
        self.work_directory = work_directory
        self.storage = work_directory / "storage"
        self.downloads = work_directory / "downloads"
        self.storage.mkdir(parents=True)
        self.downloads.mkdir()
        initial = AppConfig(
            server=ServerConfig(
                bind_address="127.0.0.1",
                port=0,
                storage_directory=self.storage,
                max_clients=max_clients,
            ),
            client=ClientConfig(
                server_address="127.0.0.1",
                server_port=1,
                download_directory=self.downloads,
            ),
            network=NetworkConfig(
                bandwidth_limit_kib_per_second=bandwidth_limit_kib_per_second,
            ),
        )
        self.listener = create_listener(initial)
        self.listener.settimeout(0.2)
        port = self.listener.getsockname()[1]
        self.config = replace(
            initial,
            server=replace(initial.server, port=port),
            client=replace(initial.client, server_port=port),
        )
        self.registry = ActiveSessionRegistry()
        self.logger = ServerLogger.from_config(self.config)
        self.workers = ClientWorkerGroup(
            self.config,
            None,
            self.logger,
            self.registry,
            FilenameLockRegistry(),
        )
        self._stop = Event()
        self._failures: Queue[BaseException] = Queue()
        self._thread = Thread(
            target=self._run,
            name="hcmus-demo-server",
            daemon=True,
        )

    def __enter__(self) -> LocalPhaseTwoServer:
        self._thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def client(self, username: str, *, download_name: str | None = None) -> ClientSession:
        download_directory = (
            self.downloads / download_name if download_name else self.downloads
        )
        config = replace(
            self.config,
            client=replace(
                self.config.client,
                download_directory=download_directory,
            ),
        )
        return ClientSession(config, username=username)

    def close(self) -> None:
        self._stop.set()
        self.listener.close()
        self.workers.close(abort_active=True)
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise RuntimeError("demo server thread did not stop")
        self.logger.close()
        try:
            failure = self._failures.get_nowait()
        except Empty:
            return
        raise RuntimeError("demo server failed") from failure

    def _run(self) -> None:
        abort_active = True
        try:
            while not self._stop.is_set():
                try:
                    accepted, peer = self.listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                if not self.workers.start(accepted, peer):
                    reject_busy(accepted, peer, self.config, self.logger)
            abort_active = False
        except BaseException as error:
            self._failures.put(error)
        finally:
            self.workers.close(abort_active=abort_active)


def new_work_directory(prefix: str, selected: Path | None) -> Path:
    work = selected or Path("runtime") / (
        prefix + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    work.mkdir(parents=True, exist_ok=False)
    return work


def wait_for(predicate: Any, *, timeout: float = 5.0) -> None:
    deadline = monotonic() + timeout
    while not predicate():
        if monotonic() >= deadline:
            raise TimeoutError("timed out waiting for server state")
        sleep(0.01)


def write_fixture(path: Path, size: int) -> bytes:
    digest = hashlib.sha256()
    pattern = bytes(range(256)) * 128
    remaining = size
    with path.open("xb") as output:
        while remaining:
            block = pattern[: min(remaining, len(pattern))]
            output.write(block)
            digest.update(block)
            remaining -= len(block)
    return digest.digest()


def sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.digest()


def throughput_kib_per_second(byte_count: int, seconds: float) -> float:
    if byte_count < 0:
        raise ValueError("byte_count must not be negative")
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    return byte_count / 1024 / seconds


def within_limit(measured: float, limit: float, tolerance_percent: float) -> bool:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if tolerance_percent < 0:
        raise ValueError("tolerance_percent must not be negative")
    return measured <= limit * (1 + tolerance_percent / 100)


def write_json_report(work: Path, filename: str, report: dict[str, object]) -> Path:
    path = work / filename
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
