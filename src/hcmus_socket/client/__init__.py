"""Interactive client package for the HCMUS socket protocol."""

from .commands import Command, CommandName, CommandSyntaxError, parse_command
from .session import ClientSession, SessionError
from .download import DownloadResult, download_file

__all__ = [
    "ClientSession",
    "Command",
    "CommandName",
    "CommandSyntaxError",
    "DownloadResult",
    "SessionError",
    "parse_command",
    "download_file",
]
