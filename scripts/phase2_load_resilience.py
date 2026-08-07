"""Demonstrate Phase 2 capacity, concurrency, and lifecycle resilience."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
from time import perf_counter

from hcmus_socket.client.listing import list_files
from hcmus_socket.client.session import AuthenticationError, ClientSession
from hcmus_socket.protocol import ErrorCode

from phase2_demo_support import (
    LocalPhaseTwoServer,
    new_work_directory,
    wait_for,
    write_json_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=int, default=10)
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--work-directory", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.clients < 1:
        raise SystemExit("clients must be positive")
    if args.cycles < 0:
        raise SystemExit("cycles must not be negative")
    work = new_work_directory("phase2-load", args.work_directory)
    started = perf_counter()
    clients: list[ClientSession] = []

    with LocalPhaseTwoServer(
        work,
        max_clients=args.clients,
        bandwidth_limit_kib_per_second=0,
    ) as server:
        try:
            clients = [server.client(f"load_user_{index}") for index in range(args.clients)]
            with ThreadPoolExecutor(max_workers=args.clients) as executor:
                list(executor.map(lambda client: client.connect(), clients))
            wait_for(lambda: server.registry.authenticated_count == args.clients)

            with ThreadPoolExecutor(max_workers=args.clients) as executor:
                listings = list(executor.map(list_files, clients))
            if any(listing.entries for listing in listings):
                raise RuntimeError("new user namespaces should initially be empty")

            overflow = server.client("overflow_user")
            try:
                try:
                    overflow.connect()
                except AuthenticationError as error:
                    if error.code is not ErrorCode.SERVER_BUSY:
                        raise
                    busy_code = error.code.name
                else:
                    raise RuntimeError("client above capacity was unexpectedly admitted")
            finally:
                overflow.close(abort=True)

            with ThreadPoolExecutor(max_workers=args.clients) as executor:
                list(executor.map(lambda client: client.disconnect(), clients))
            clients.clear()
            wait_for(
                lambda: server.registry.active_count == 0
                and server.workers.active_count == 0
            )

            # A broken peer must only terminate its own worker. Sending a full,
            # invalid preface avoids depending on a socket read timeout.
            with socket.create_connection(
                (server.config.client.server_address, server.config.client.server_port),
                timeout=server.config.client.connect_timeout_ms / 1000,
            ) as malformed:
                malformed.sendall(b"NOT-HCMU")
            wait_for(lambda: server.workers.active_count == 0)

            recovery = server.client("recovery_user")
            try:
                recovery.connect()
                recovery_listing = list_files(recovery)
                recovery.disconnect()
            finally:
                recovery.close(abort=True)
            if recovery_listing.entries:
                raise RuntimeError("recovery user namespace should initially be empty")
            wait_for(
                lambda: server.registry.active_count == 0
                and server.workers.active_count == 0
            )

            for cycle in range(args.cycles):
                client = server.client(f"cycle_user_{cycle}")
                try:
                    client.connect()
                    list_files(client)
                    client.disconnect()
                finally:
                    client.close(abort=True)
            wait_for(
                lambda: server.registry.active_count == 0
                and server.workers.active_count == 0
            )

            log_lines = server.logger.path.read_text(encoding="utf-8").splitlines()
            log_events = [json.loads(line) for line in log_lines]
            logger_status = server.logger.status()
            if logger_status.failed_writes:
                raise RuntimeError("server logger reported failed writes")

            report = {
                "result": "PASS",
                "simultaneous_clients": args.clients,
                "overflow_error_code": busy_code,
                "connect_list_disconnect_cycles": args.cycles,
                "invalid_preface_isolated": True,
                "listener_accepted_recovery_client": True,
                "active_sessions_after_test": server.registry.active_count,
                "active_workers_after_test": server.workers.active_count,
                "parseable_json_log_events": len(log_events),
                "logger_failed_writes": logger_status.failed_writes,
                "duration_seconds": round(perf_counter() - started, 3),
            }
            report_path = write_json_report(work, "load-resilience.json", report)
            print(json.dumps(report, indent=2))
            print(f"Report: {report_path}")
        finally:
            for client in clients:
                client.close(abort=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
