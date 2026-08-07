"""Interactive client package for the HCMUS socket protocol."""

from .commands import Command, CommandName, CommandSyntaxError, parse_command
from .session import AuthenticationError, ClientSession, SessionError
from .download import DownloadResult, download_file
from .listing import list_files
from .upload import UploadResult, upload_file
from .api import ClientApi, ProgressCallback

__all__ = [
    "ClientSession",
    "ClientApi",
    "AuthenticationError",
    "Command",
    "CommandName",
    "CommandSyntaxError",
    "DownloadResult",
    "ProgressCallback",
    "SessionError",
    "UploadResult",
    "parse_command",
    "download_file",
    "list_files",
    "upload_file",
]
