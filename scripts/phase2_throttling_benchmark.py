"""Measure per-client Phase 2 throttling through real loopback TCP transfers."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from time import perf_counter

from hcmus_socket.client.download import download_file
from hcmus_socket.client.session import ClientSession
from hcmus_socket.client.upload import upload_file
from hcmus_socket.config import AppConfig

from phase2_demo_support import (
    LocalPhaseTwoServer,
    new_work_directory,
    sha256,
    throughput_kib_per_second,
    wait_for,
    within_limit,
    write_fixture,
    write_json_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=int, default=2)
    parser.add_argument(
        "--size",
        type=int,
        default=3 * 1024 * 1024,
        help="bytes per transfer; must provide at least five steady-state seconds",
    )
    parser.add_argument("--limit-kib-per-second", type=int, default=500)
    parser.add_argument("--tolerance-percent", type=float, default=10.0)
    parser.add_argument("--work-directory", type=Path)
    return parser


def _timed_upload(client: ClientSession, source: Path) -> tuple[float, bytes]:
    started = perf_counter()
    result = upload_file(client, source, source.name)
    return perf_counter() - started, result.sha256_digest


def _timed_download(client: ClientSession, filename: str) -> tuple[float, Path, bytes]:
    started = perf_counter()
    result = download_file(client, filename)
    return perf_counter() - started, result.path, result.sha256_digest


def main() -> int:
    args = build_parser().parse_args()
    if args.clients < 1:
        raise SystemExit("clients must be positive")
    if args.size <= 0:
        raise SystemExit("size must be positive")
    if args.limit_kib_per_second <= 0:
        raise SystemExit("limit must be positive")
    if args.tolerance_percent < 0:
        raise SystemExit("tolerance must not be negative")

    minimum_size = (
        args.limit_kib_per_second * 1024 * 5
        + AppConfig().network.chunk_size_bytes
    )
    if args.size < minimum_size:
        raise SystemExit(
            "size is too small for a stable five-second measurement; "
            f"use at least {minimum_size} bytes for this limit"
        )

    work = new_work_directory("phase2-throttle", args.work_directory)
    sources = work / "sources"
    sources.mkdir()
    clients: list[ClientSession] = []
    expected: dict[str, bytes] = {}

    with LocalPhaseTwoServer(
        work,
        max_clients=args.clients,
        bandwidth_limit_kib_per_second=args.limit_kib_per_second,
    ) as server:
        try:
            for index in range(args.clients):
                filename = f"throttle-{index}-{args.size}.bin"
                expected[filename] = write_fixture(sources / filename, args.size)
                clients.append(
                    server.client(f"throttle_user_{index}", download_name=f"client-{index}")
                )
            with ThreadPoolExecutor(max_workers=args.clients) as executor:
                list(executor.map(lambda client: client.connect(), clients))
            wait_for(lambda: server.registry.authenticated_count == args.clients)

            upload_wall_started = perf_counter()
            with ThreadPoolExecutor(max_workers=args.clients) as executor:
                uploads = list(
                    executor.map(
                        lambda pair: _timed_upload(pair[0], pair[1]),
                        zip(clients, sorted(sources.iterdir()), strict=True),
                    )
                )
            upload_wall = perf_counter() - upload_wall_started

            download_wall_started = perf_counter()
            with ThreadPoolExecutor(max_workers=args.clients) as executor:
                downloads = list(
                    executor.map(
                        lambda pair: _timed_download(pair[0], pair[1]),
                        zip(clients, sorted(expected), strict=True),
                    )
                )
            download_wall = perf_counter() - download_wall_started

            rows: list[dict[str, object]] = []
            all_within_limit = True
            for index, filename in enumerate(sorted(expected)):
                upload_seconds, upload_digest = uploads[index]
                download_seconds, downloaded_path, download_digest = downloads[index]
                upload_speed = throughput_kib_per_second(args.size, upload_seconds)
                download_speed = throughput_kib_per_second(args.size, download_seconds)
                upload_ok = within_limit(
                    upload_speed, args.limit_kib_per_second, args.tolerance_percent
                )
                download_ok = within_limit(
                    download_speed, args.limit_kib_per_second, args.tolerance_percent
                )
                checksum_ok = (
                    upload_digest
                    == download_digest
                    == sha256(downloaded_path)
                    == expected[filename]
                )
                all_within_limit &= upload_ok and download_ok and checksum_ok
                rows.append(
                    {
                        "client": index,
                        "filename": filename,
                        "upload_seconds": round(upload_seconds, 3),
                        "upload_kib_s": round(upload_speed, 3),
                        "upload_within_limit": upload_ok,
                        "download_seconds": round(download_seconds, 3),
                        "download_kib_s": round(download_speed, 3),
                        "download_within_limit": download_ok,
                        "checksum_match": checksum_ok,
                    }
                )

            for client in clients:
                client.disconnect()
            clients.clear()
            wait_for(lambda: server.registry.active_count == 0)
            report = {
                "result": "PASS" if all_within_limit else "FAIL",
                "clients": args.clients,
                "bytes_per_transfer": args.size,
                "limit_kib_per_second": args.limit_kib_per_second,
                "tolerance_percent": args.tolerance_percent,
                "maximum_allowed_kib_s": args.limit_kib_per_second
                * (1 + args.tolerance_percent / 100),
                "concurrent_upload_wall_seconds": round(upload_wall, 3),
                "concurrent_download_wall_seconds": round(download_wall, 3),
                "measurements": rows,
            }
            report_path = write_json_report(
                work, "throttling-benchmark.json", report
            )
            print(json.dumps(report, indent=2))
            print(f"Report: {report_path}")
            if not all_within_limit:
                raise SystemExit(1)
        finally:
            for client in clients:
                client.close(abort=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
