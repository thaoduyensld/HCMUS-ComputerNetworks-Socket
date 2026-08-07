from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hcmus_socket.common.partial_transfer import save_part_metadata


def test_metadata_replace_retries_transient_windows_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta_path = tmp_path / "data.bin.part.meta"
    original_replace = os.replace
    calls = 0

    def flaky_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("temporarily locked")
        original_replace(source, destination)

    monkeypatch.setattr("hcmus_socket.common.partial_transfer.os.replace", flaky_replace)
    monkeypatch.setattr("hcmus_socket.common.partial_transfer.sleep", lambda _delay: None)

    save_part_metadata(meta_path, total_size=100, uploaded_bytes=40)

    assert calls == 3
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "total_size": 100,
        "uploaded_bytes": 40,
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_metadata_replace_reports_permanent_failure_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta_path = tmp_path / "data.bin.part.meta"

    def fail_replace(_source: str | Path, _destination: str | Path) -> None:
        raise PermissionError("permanently locked")

    monkeypatch.setattr("hcmus_socket.common.partial_transfer.os.replace", fail_replace)
    monkeypatch.setattr("hcmus_socket.common.partial_transfer.sleep", lambda _delay: None)

    with pytest.raises(PermissionError, match="permanently locked"):
        save_part_metadata(meta_path, total_size=100, uploaded_bytes=40)

    assert not meta_path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
