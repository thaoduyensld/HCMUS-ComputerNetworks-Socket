"""Parsing for the three public file-transfer commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import shlex


class CommandSyntaxError(ValueError):
    """Raised when a line is not a valid client command."""


class CommandName(str, Enum):
    LIST = "LIST"
    UPLOAD = "UPLOAD"
    DOWNLOAD = "DOWNLOAD"
    QUIT = "QUIT"  # Local session control; not a fourth file operation.


@dataclass(frozen=True, slots=True)
class Command:
    name: CommandName
    filename: str | None = None


def parse_command(line: str) -> Command:
    """Parse one CLI line, accepting quoted filenames and case-insensitive verbs."""

    if not isinstance(line, str):
        raise CommandSyntaxError("command must be text")
    try:
        parts = shlex.split(line, posix=True)
    except ValueError as error:
        raise CommandSyntaxError(f"invalid quoting: {error}") from error
    if not parts:
        raise CommandSyntaxError("command must not be empty")

    verb = parts[0].upper()
    try:
        name = CommandName(verb)
    except ValueError as error:
        raise CommandSyntaxError(
            "unknown command; use LIST, UPLOAD <filename>, or DOWNLOAD <filename>"
        ) from error

    arguments = parts[1:]
    if name in {CommandName.LIST, CommandName.QUIT}:
        if arguments:
            raise CommandSyntaxError(f"{name.value} does not accept arguments")
        return Command(name)

    if len(arguments) != 1:
        raise CommandSyntaxError(f"usage: {name.value} <filename>")
    return Command(name, arguments[0])
