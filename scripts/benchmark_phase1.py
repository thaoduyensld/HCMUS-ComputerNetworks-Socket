"""Run repeatable Phase 2 upload/download benchmarks over loopback TCP."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
from queue import Queue
from threading import Thread
from time import perf_counter
import tracemalloc

from hcmus_socket.client.download import download_file
from hcmus_socket.client.session import ClientSession
from hcmus_socket.client.upload import upload_file
from hcmus_socket.config import AppConfig, ClientConfig, NetworkConfig, ServerConfig
from hcmus_socket.server.app import create_listener, serve_client
from hcmus_socket.server.logger import ServerLogger


DEFAULT_SIZES = (512, 10 * 1024 * 1024, 120 * 1024 * 1024)
DEFAULT_USERNAME = "benchmark_user"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark Phase 2 UPLOAD and DOWNLOAD over loopback TCP",
    )
    parser.add_argument(
        "--work-directory",
        type=Path,
        help="new directory for generated files, downloads, logs, and results",
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=list(DEFAULT_SIZES),
        help="file sizes in bytes (default: 512, 10 MiB, 120 MiB)",
    )
    parser.add_argument(
        "--username",
        default=DEFAULT_USERNAME,
        help=f"Phase 2 login username (default: {DEFAULT_USERNAME})",
    )
    parser.add_argument(
        "--bandwidth-limit-kib-per-second",
        type=int,
        default=0,
        help="per-client limit; 0 disables throttling for maximum-speed measurements",
    )
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if any(size < 0 for size in arguments.sizes):
        raise SystemExit("benchmark sizes must not be negative")
    if arguments.bandwidth_limit_kib_per_second < 0:
        raise SystemExit("bandwidth limit must not be negative")

    work = arguments.work_directory or Path("runtime") / (
        "benchmark-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    work.mkdir(parents=True, exist_ok=False)
    sources = work / "sources"
    storage = work / "storage"
    downloads = work / "downloads"
    sources.mkdir()
    storage.mkdir()

    base_config = AppConfig(
        server=ServerConfig(
            bind_address="127.0.0.1",
            port=0,
            storage_directory=storage,
        ),
        client=ClientConfig(
            server_address="127.0.0.1",
            server_port=1,
            download_directory=downloads,
        ),
        network=NetworkConfig(
            bandwidth_limit_kib_per_second=(
                arguments.bandwidth_limit_kib_per_second
            ),
        ),
    )
    listener = create_listener(base_config)
    port = listener.getsockname()[1]
    config = replace(
        base_config,
        server=replace(base_config.server, port=port),
        client=replace(base_config.client, server_port=port),
    )
    logger = ServerLogger.from_config(config)

    server_failures: Queue[BaseException] = Queue()

    def run_server() -> None:
        try:
            accepted, peer = listener.accept()
            serve_client(accepted, peer, config, logger=logger)
        except BaseException as error:
            server_failures.put(error)

    rows: list[dict[str, object]] = []
    client = ClientSession(config, username=arguments.username)
    server_thread = Thread(
        target=run_server,
        name="hcmus-benchmark-server",
        daemon=True,
    )
    tracemalloc.start()
    server_thread.start()
    try:
        client.connect()
        for index, size in enumerate(arguments.sizes):
            name = f"benchmark-{index}-{size}.bin"
            source = sources / name
            _write_fixture(source, size)
            expected_digest = _sha256(source)

            tracemalloc.reset_peak()
            started = perf_counter()
            upload = upload_file(client, source, name)
            upload_seconds = perf_counter() - started
            upload_peak = tracemalloc.get_traced_memory()[1]

            tracemalloc.reset_peak()
            started = perf_counter()
            download = download_file(client, name)
            download_seconds = perf_counter() - started
            download_peak = tracemalloc.get_traced_memory()[1]

            actual_digest = _sha256(download.path)
            if upload.sha256_digest != expected_digest:
                raise RuntimeError(f"upload checksum mismatch for {name}")
            if download.sha256_digest != expected_digest:
                raise RuntimeError(f"download checksum mismatch for {name}")
            if actual_digest != expected_digest:
                raise RuntimeError(f"downloaded file mismatch for {name}")

            rows.append(
                {
                    "filename": name,
                    "bytes": size,
                    "sha256": expected_digest.hex(),
                    "upload_seconds": round(upload_seconds, 6),
                    "upload_kib_s": _speed(size, upload_seconds),
                    "upload_peak_traced_bytes": upload_peak,
                    "download_seconds": round(download_seconds, 6),
                    "download_kib_s": _speed(size, download_seconds),
                    "download_peak_traced_bytes": download_peak,
                }
            )
        client.disconnect()
    finally:
        client.close(abort=True)
        listener.close()
        server_thread.join(timeout=5)
        logger.close()
        tracemalloc.stop()
        if server_thread.is_alive():
            raise RuntimeError("benchmark server thread did not stop")
        if not server_failures.empty():
            raise RuntimeError("benchmark server failed") from server_failures.get()

    report = {
        "work_directory": str(work.resolve()),
        "username": arguments.username,
        "chunk_size_bytes": config.network.chunk_size_bytes,
        "max_payload_bytes": config.network.max_payload_bytes,
        "bandwidth_limit_kib_per_second": (
            config.network.bandwidth_limit_kib_per_second
        ),
        "results": rows,
    }
    report_path = work / "benchmark.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _write_fixture(path: Path, size: int) -> None:
    pattern = bytes(range(256)) * 128
    remaining = size
    with path.open("xb") as output:
        while remaining:
            block = pattern[: min(remaining, len(pattern))]
            output.write(block)
            remaining -= len(block)


def _sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(1024 * 1024):
            digest.update(data)
    return digest.digest()


def _speed(size: int, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return round(size / 1024 / seconds, 3)


if __name__ == "__main__":
    raise SystemExit(main())
