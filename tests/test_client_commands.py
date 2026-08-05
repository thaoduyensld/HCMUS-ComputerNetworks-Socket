from __future__ import annotations

import pytest

from hcmus_socket.client.commands import (
    Command,
    CommandName,
    CommandSyntaxError,
    parse_command,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("LIST", Command(CommandName.LIST)),
        ("list", Command(CommandName.LIST)),
        ("UPLOAD data.bin", Command(CommandName.UPLOAD, "data.bin")),
        ("download data.bin", Command(CommandName.DOWNLOAD, "data.bin")),
        ('DOWNLOAD "file with spaces.bin"', Command(CommandName.DOWNLOAD, "file with spaces.bin")),
        ("QUIT", Command(CommandName.QUIT)),
    ],
)
def test_parse_valid_commands(line: str, expected: Command) -> None:
    assert parse_command(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "DELETE data.bin",
        "LIST unexpected",
        "UPLOAD",
        "UPLOAD one two",
        "DOWNLOAD",
        "DOWNLOAD one two",
        "QUIT unexpected",
        'DOWNLOAD "unterminated',
    ],
)
def test_reject_invalid_commands(line: str) -> None:
    with pytest.raises(CommandSyntaxError):
        parse_command(line)
