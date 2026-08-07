from __future__ import annotations

import os
from pathlib import Path

from hcmus_socket.config import AppConfig, ServerConfig
from hcmus_socket.server.app import serve_forever
from hcmus_socket.server.cleanup import cleanup_expired_partials


def _set_mtime(path: Path, value: float) -> None:
    os.utime(path, (value, value))


def test_cleanup_removes_expired_partial_as_a_pair(tmp_path: Path) -> None:
    namespace = tmp_path / "alice"
    namespace.mkdir()
    part = namespace / "data.bin.part"
    metadata = namespace / "data.bin.part.meta"
    part.write_bytes(b"partial")
    metadata.write_text("{}", encoding="utf-8")
    _set_mtime(part, 100.0)
    _set_mtime(metadata, 100.0)

    assert cleanup_expired_partials(tmp_path, 10, now=111.0) == 2
    assert not part.exists()
    assert not metadata.exists()


def test_fresh_pair_member_prevents_cleanup(tmp_path: Path) -> None:
    part = tmp_path / "data.bin.part"
    metadata = tmp_path / "data.bin.part.meta"
    part.write_bytes(b"partial")
    metadata.write_text("{}", encoding="utf-8")
    _set_mtime(part, 1.0)
    _set_mtime(metadata, 105.0)

    assert cleanup_expired_partials(tmp_path, 10, now=111.0) == 0
    assert part.exists()
    assert metadata.exists()


def test_zero_ttl_disables_cleanup(tmp_path: Path) -> None:
    part = tmp_path / "data.bin.part"
    part.write_bytes(b"partial")
    _set_mtime(part, 1.0)

    assert cleanup_expired_partials(tmp_path, 0, now=10_000.0) == 0
    assert part.exists()


def test_server_startup_applies_partial_ttl(tmp_path: Path) -> None:
    namespace = tmp_path / "alice"
    namespace.mkdir()
    part = namespace / "old.bin.part"
    metadata = namespace / "old.bin.part.meta"
    part.write_bytes(b"partial")
    metadata.write_text("{}", encoding="utf-8")
    _set_mtime(part, 1.0)
    _set_mtime(metadata, 1.0)

    class StoppingListener:
        def accept(self) -> object:
            raise KeyboardInterrupt

        def close(self) -> None:
            pass

    serve_forever(
        AppConfig(
            server=ServerConfig(
                storage_directory=tmp_path,
                partial_ttl_seconds=1,
            )
        ),
        listener=StoppingListener(),  # type: ignore[arg-type]
    )

    assert not part.exists()
    assert not metadata.exists()
