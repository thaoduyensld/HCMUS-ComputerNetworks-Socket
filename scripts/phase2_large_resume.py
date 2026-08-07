"""Demonstrate interrupted Upload/Download resume for 10 MiB and 120 MiB files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from hcmus_socket.client.download import download_file
from hcmus_socket.client.session import ClientSession
from hcmus_socket.client.upload import upload_file
from hcmus_socket.common.partial_transfer import load_part_metadata
from hcmus_socket.messages import (
    Acknowledgement,
    FileChunk,
    FileDownload,
    FileUpload,
    make_acknowledgement_frame,
    make_file_chunk_frame,
    make_file_download_frame,
    make_file_upload_frame,
    parse_acknowledgement,
    parse_file_chunk,
    parse_file_info,
)
from hcmus_socket.protocol import Opcode

from phase2_demo_support import (
    LocalPhaseTwoServer,
    new_work_directory,
    sha256,
    wait_for,
    write_fixture,
    write_json_report,
)


DEFAULT_SIZES = (10 * 1024 * 1024, 120 * 1024 * 1024)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--interrupt-ratio", type=float, default=0.5)
    parser.add_argument("--work-directory", type=Path)
    return parser


def _wait_for_disconnect(server: LocalPhaseTwoServer) -> None:
    wait_for(
        lambda: server.registry.active_count == 0
        and server.workers.active_count == 0,
        timeout=15.0,
    )


def _interrupt_upload(
    server: LocalPhaseTwoServer,
    username: str,
    source: Path,
    cutoff: int,
) -> int:
    client = server.client(username)
    try:
        client.connect()
        maximum = client.config.network.max_payload_bytes
        chunk_size = client.config.network.chunk_size_bytes
        total_size = source.stat().st_size
        client.send(
            make_file_upload_frame(
                FileUpload(source.name, total_size, start_offset=0),
                maximum,
                user_id=client.user_id,
            )
        )
        acknowledgement = parse_acknowledgement(client.receive(), maximum)
        if (
            acknowledgement.acknowledged_opcode is not Opcode.FILE_UPLOAD
            or acknowledgement.next_offset != 0
        ):
            raise RuntimeError("server did not start the interrupted upload at zero")

        sent = 0
        with source.open("rb") as input_file:
            while sent < cutoff:
                block = input_file.read(min(chunk_size, cutoff - sent))
                if not block:
                    raise RuntimeError("source ended before the interruption offset")
                client.send(
                    make_file_chunk_frame(
                        FileChunk(sent, block),
                        chunk_size,
                        maximum,
                        user_id=client.user_id,
                    )
                )
                sent += len(block)

        metadata_path = (
            server.storage / username / f"{source.name}.part.meta"
        )

        def offset_is_persisted() -> bool:
            metadata = load_part_metadata(metadata_path)
            return metadata is not None and metadata.get("uploaded_bytes") == sent

        wait_for(offset_is_persisted, timeout=15.0)
        return sent
    finally:
        client.close(abort=True)


def _resume_upload(
    server: LocalPhaseTwoServer,
    username: str,
    source: Path,
) -> tuple[int, bytes, float]:
    client = server.client(username)
    resumed_from: int | None = None

    def progress(done: int, _total: int, _percent: int) -> None:
        nonlocal resumed_from
        if resumed_from is None:
            resumed_from = done

    started = perf_counter()
    try:
        client.connect()
        result = upload_file(client, source, progress=progress)
        client.disconnect()
    finally:
        client.close(abort=True)
    if resumed_from is None:
        raise RuntimeError("upload did not report its negotiated resume offset")
    return resumed_from, result.sha256_digest, perf_counter() - started


def _interrupt_download(
    server: LocalPhaseTwoServer,
    username: str,
    filename: str,
    cutoff: int,
    download_name: str,
) -> tuple[int, Path]:
    client = server.client(username, download_name=download_name)
    try:
        client.connect()
        maximum = client.config.network.max_payload_bytes
        client.send(
            make_file_download_frame(
                FileDownload(filename, requested_offset=0),
                maximum,
                user_id=client.user_id,
            )
        )
        info = parse_file_info(client.receive(), maximum)
        if info.start_offset != 0:
            raise RuntimeError("server did not start the interrupted download at zero")
        client.send(
            make_acknowledgement_frame(
                Acknowledgement(Opcode.FILE_INFO, 0),
                maximum,
                user_id=client.user_id,
            )
        )

        part_path = client.config.client.download_directory / f"{filename}.part"
        part_path.parent.mkdir(parents=True, exist_ok=True)
        received = 0
        with part_path.open("xb") as output:
            while received < cutoff:
                chunk = parse_file_chunk(
                    client.receive(),
                    client.config.network.chunk_size_bytes,
                    maximum,
                )
                if chunk.offset != received:
                    raise RuntimeError("download chunk offset is not contiguous")
                output.write(chunk.data)
                received += len(chunk.data)
        return received, part_path
    finally:
        client.close(abort=True)


def _resume_download(
    server: LocalPhaseTwoServer,
    username: str,
    filename: str,
    download_name: str,
) -> tuple[int, Path, bytes, float]:
    client = server.client(username, download_name=download_name)
    resumed_from: int | None = None

    def progress(done: int, _total: int, _percent: int) -> None:
        nonlocal resumed_from
        if resumed_from is None:
            resumed_from = done

    started = perf_counter()
    try:
        client.connect()
        result = download_file(client, filename, progress=progress)
        client.disconnect()
    finally:
        client.close(abort=True)
    if resumed_from is None:
        raise RuntimeError("download did not report its requested resume offset")
    return (
        resumed_from,
        result.path,
        result.sha256_digest,
        perf_counter() - started,
    )


def main() -> int:
    args = build_parser().parse_args()
    if any(size <= 0 for size in args.sizes):
        raise SystemExit("all sizes must be positive")
    if not 0.0 < args.interrupt_ratio < 1.0:
        raise SystemExit("interrupt-ratio must be between zero and one")

    work = new_work_directory("phase2-large-resume", args.work_directory)
    sources = work / "sources"
    sources.mkdir()
    report_rows: list[dict[str, object]] = []
    overall_started = perf_counter()

    with LocalPhaseTwoServer(
        work,
        max_clients=2,
        bandwidth_limit_kib_per_second=0,
    ) as server:
        for index, size in enumerate(args.sizes):
            filename = f"resume-{size}.bin"
            source = sources / filename
            expected_digest = write_fixture(source, size)
            username = f"large_resume_{index}"
            cutoff = int(size * args.interrupt_ratio)

            uploaded_before_disconnect = _interrupt_upload(
                server, username, source, cutoff
            )
            _wait_for_disconnect(server)
            upload_resumed_from, upload_digest, upload_seconds = _resume_upload(
                server, username, source
            )
            _wait_for_disconnect(server)

            download_name = f"large-resume-client-{index}"
            downloaded_before_disconnect, part_path = _interrupt_download(
                server,
                username,
                filename,
                cutoff,
                download_name,
            )
            _wait_for_disconnect(server)
            (
                download_resumed_from,
                downloaded_path,
                download_digest,
                download_seconds,
            ) = _resume_download(server, username, filename, download_name)
            _wait_for_disconnect(server)

            published_path = server.storage / username / filename
            checksum_match = (
                upload_digest
                == download_digest
                == sha256(published_path)
                == sha256(downloaded_path)
                == expected_digest
            )
            offsets_match = (
                upload_resumed_from == uploaded_before_disconnect
                and download_resumed_from == downloaded_before_disconnect
            )
            if not checksum_match or not offsets_match or part_path.exists():
                raise RuntimeError(f"large resume validation failed for {size} bytes")

            report_rows.append(
                {
                    "filename": filename,
                    "bytes": size,
                    "interrupt_ratio": args.interrupt_ratio,
                    "upload_resumed_from": upload_resumed_from,
                    "download_resumed_from": download_resumed_from,
                    "upload_resume_seconds": round(upload_seconds, 3),
                    "download_resume_seconds": round(download_seconds, 3),
                    "checksum_match": True,
                    "sha256": expected_digest.hex(),
                }
            )

        report = {
            "result": "PASS",
            "transport": "real TCP loopback",
            "sizes": args.sizes,
            "interrupt_ratio": args.interrupt_ratio,
            "measurements": report_rows,
            "duration_seconds": round(perf_counter() - overall_started, 3),
        }
        report_path = write_json_report(work, "large-resume.json", report)
        print(json.dumps(report, indent=2))
        print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
