from __future__ import annotations

import pytest

from hcmus_socket.ui.app import TransferProgress
from hcmus_socket.ui.file_view import format_size


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


def test_transfer_progress_keeps_ui_metadata_together() -> None:
    progress = TransferProgress("Uploading", "data.bin", 512, 1024, 50)

    assert progress.action == "Uploading"
    assert progress.filename == "data.bin"
    assert (progress.done, progress.total, progress.percent) == (512, 1024, 50)
