from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hcmus_socket.common.partial_transfer import load_part_metadata
from hcmus_socket.client.download import download_file
from hcmus_socket.client.upload import upload_file
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
from scripts.phase2_demo_support import LocalPhaseTwoServer, wait_for


FILE_SIZE = 320 * 1024 + 137


def _fixture(path: Path) -> bytes:
    data = (bytes(range(256)) * ((FILE_SIZE // 256) + 1))[:FILE_SIZE]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _wait_for_disconnect(server: LocalPhaseTwoServer) -> None:
    wait_for(
        lambda: server.registry.active_count == 0
        and server.workers.active_count == 0
    )


@pytest.mark.parametrize("interrupt_ratio", [0.3, 0.5, 0.7])
def test_upload_resumes_after_real_tcp_disconnect(
    tmp_path: Path,
    interrupt_ratio: float,
) -> None:
    source = tmp_path / "source.bin"
    contents = _fixture(source)
    cutoff = int(len(contents) * interrupt_ratio)
    username = f"upload-{int(interrupt_ratio * 100)}"

    with LocalPhaseTwoServer(
        tmp_path / "server-run",
        max_clients=2,
        bandwidth_limit_kib_per_second=0,
    ) as server:
        first = server.client(username)
        try:
            first.connect()
            maximum = first.config.network.max_payload_bytes
            chunk_size = first.config.network.chunk_size_bytes
            first.send(
                make_file_upload_frame(
                    FileUpload(source.name, len(contents), start_offset=0),
                    maximum,
                    user_id=first.user_id,
                )
            )
            acknowledgement = parse_acknowledgement(first.receive(), maximum)
            assert acknowledgement.acknowledged_opcode is Opcode.FILE_UPLOAD
            assert acknowledgement.next_offset == 0

            sent = 0
            while sent < cutoff:
                block = contents[sent : min(cutoff, sent + chunk_size)]
                first.send(
                    make_file_chunk_frame(
                        FileChunk(sent, block),
                        chunk_size,
                        maximum,
                        user_id=first.user_id,
                    )
                )
                sent += len(block)

            namespace = server.storage / username
            partial = namespace / f"{source.name}.part"
            metadata = namespace / f"{source.name}.part.meta"

            def persisted_to_cutoff() -> bool:
                loaded = load_part_metadata(metadata)
                return loaded is not None and loaded.get("uploaded_bytes") == cutoff

            wait_for(persisted_to_cutoff)
        finally:
            first.close(abort=True)
        _wait_for_disconnect(server)

        progress: list[tuple[int, int, int]] = []
        resumed = server.client(username)
        try:
            resumed.connect()
            result = upload_file(
                resumed,
                source,
                progress=lambda done, total, percent: progress.append(
                    (done, total, percent)
                ),
            )
            resumed.disconnect()
        finally:
            resumed.close(abort=True)

        published = namespace / source.name
        assert progress[0][0] == cutoff
        assert result.sha256_digest == hashlib.sha256(contents).digest()
        assert published.read_bytes() == contents
        assert not partial.exists()
        assert not metadata.exists()


@pytest.mark.parametrize("interrupt_ratio", [0.3, 0.5, 0.7])
def test_download_resumes_after_real_tcp_disconnect(
    tmp_path: Path,
    interrupt_ratio: float,
) -> None:
    filename = "download.bin"
    username = f"download-{int(interrupt_ratio * 100)}"

    with LocalPhaseTwoServer(
        tmp_path / "server-run",
        max_clients=2,
        bandwidth_limit_kib_per_second=0,
    ) as server:
        contents = _fixture(server.storage / username / filename)
        first = server.client(username, download_name="resume-client")
        first.connect()
        maximum = first.config.network.max_payload_bytes
        first.send(
            make_file_download_frame(
                FileDownload(filename, requested_offset=0),
                maximum,
                user_id=first.user_id,
            )
        )
        info = parse_file_info(first.receive(), maximum)
        assert info.start_offset == 0
        first.send(
            make_acknowledgement_frame(
                Acknowledgement(Opcode.FILE_INFO, 0),
                maximum,
                user_id=first.user_id,
            )
        )

        part = first.config.client.download_directory / f"{filename}.part"
        part.parent.mkdir(parents=True, exist_ok=True)
        target = int(len(contents) * interrupt_ratio)
        received = 0
        with part.open("wb") as output:
            while received < target:
                chunk = parse_file_chunk(
                    first.receive(),
                    first.config.network.chunk_size_bytes,
                    maximum,
                )
                assert chunk.offset == received
                output.write(chunk.data)
                received += len(chunk.data)
        assert 0.3 <= received / len(contents) <= 0.8
        first.close(abort=True)
        _wait_for_disconnect(server)

        progress: list[tuple[int, int, int]] = []
        resumed = server.client(username, download_name="resume-client")
        try:
            resumed.connect()
            result = download_file(
                resumed,
                filename,
                progress=lambda done, total, percent: progress.append(
                    (done, total, percent)
                ),
            )
            resumed.disconnect()
        finally:
            resumed.close(abort=True)

        assert progress[0][0] == received
        assert result.path.read_bytes() == contents
        assert result.sha256_digest == hashlib.sha256(contents).digest()
        assert not part.exists()
