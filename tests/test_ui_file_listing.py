from __future__ import annotations

import pytest

from hcmus_socket.ui.app import TransferProgress
from hcmus_socket.ui.file_view import format_size, normalize_layout
from hcmus_socket.ui.theme import palette_for
from hcmus_socket.ui.transfer_view import (
    TransferSnapshot,
    TransferTracker,
    format_duration,
    format_transfer_detail,
)


@pytest.mark.parametrize(
    ("size", "formatted"),
    [
        (0, "0 B"),
        (1, "1 B"),
        (1023, "1023 B"),
        (1024, "1.00 KiB"),
        (1536, "1.50 KiB"),
        (1024**2, "1.00 MiB"),
        (5 * 1024**3, "5.00 GiB"),
    ],
)
def test_format_size(size: int, formatted: str) -> None:
    assert format_size(size) == formatted


def test_format_size_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="negative"):
        format_size(-1)


def test_file_layout_accepts_list_and_grid_only() -> None:
    assert normalize_layout("list") == "list"
    assert normalize_layout("grid") == "grid"
    with pytest.raises(ValueError, match="layout"):
        normalize_layout("cards")


def test_light_and_dark_palettes_have_distinct_surfaces() -> None:
    light = palette_for("light")
    dark = palette_for("dark")

    assert light["window"] != dark["window"]
    assert light["card"] != dark["card"]
    assert set(light) == set(dark)
    with pytest.raises(ValueError, match="theme mode"):
        palette_for("system")


def test_transfer_progress_keeps_ui_metadata_together() -> None:
    progress = TransferProgress("Uploading", "data.bin", 512, 1024, 50)

    assert progress.action == "Uploading"
    assert progress.filename == "data.bin"
    assert (progress.done, progress.total, progress.percent) == (512, 1024, 50)


def test_transfer_tracker_excludes_resumed_prefix_from_speed() -> None:
    tracker = TransferTracker()

    first = tracker.update(256, 1024, now=10.0)
    second = tracker.update(768, 1024, now=12.0)

    assert first == TransferSnapshot(0.0, None, 256)
    assert second.bytes_per_second == 256
    assert second.eta_seconds == 1
    assert second.resumed_from == 256


def test_transfer_detail_includes_speed_eta_and_resume_offset() -> None:
    detail = format_transfer_detail(
        768,
        1024,
        75,
        TransferSnapshot(256.0, 1.0, 256),
    )

    assert detail == "768 B / 1.00 KiB (75%) | 256 B/s | ETA 1s | resumed at 256 B"


@pytest.mark.parametrize(
    ("seconds", "formatted"),
    [(0, "0s"), (0.1, "1s"), (61, "1m 1s"), (3661, "1h 1m")],
)
def test_format_duration(seconds: float, formatted: str) -> None:
    assert format_duration(seconds) == formatted
