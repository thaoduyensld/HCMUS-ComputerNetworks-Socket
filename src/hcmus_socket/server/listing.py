"""FILE_LIST handling for server storage."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import TYPE_CHECKING

from ..messages import (
    ErrorMessage,
    FileEntry,
    FileListResponse,
    make_error_frame,
    make_file_list_response_frame,
    parse_file_list,
)
from ..protocol import ErrorCode, Frame, Opcode, ProtocolError

if TYPE_CHECKING:
    from .session import ServerSession


INTERNAL_FILENAMES = frozenset(
    {".hcmus_socket.lock", ".hcmus_socket.log", "server.log"}
)


def handle_file_list(session: ServerSession, frame: Frame) -> Frame:
    """Validate FILE_LIST and send a response or recoverable filesystem error."""

    parse_file_list(frame, session.config.network.max_payload_bytes)
    try:
        entries = list_storage(session.config.server.storage_directory)
        response = make_file_list_response_frame(
            FileListResponse(entries),
            max_payload_bytes=session.config.network.max_payload_bytes,
        )
    except PermissionError as error:
        response = _listing_error(ErrorCode.ACCESS_DENIED, str(error), session)
    except OSError as error:
        response = _listing_error(ErrorCode.FILE_IO_ERROR, str(error), session)
    except ProtocolError as error:
        if error.code is not ErrorCode.PAYLOAD_TOO_LARGE:
            raise
        response = _listing_error(
            ErrorCode.LIST_TOO_LARGE,
            "file list exceeds the configured payload limit",
            session,
        )
    session.send(response)
    return response


def list_storage(storage_directory: Path) -> tuple[FileEntry, ...]:
    """Return sorted metadata for public regular files in storage."""

    entries: list[FileEntry] = []
    for path in storage_directory.iterdir():
        if path.name.endswith(".part") or path.name in INTERNAL_FILENAMES:
            continue
        if path.is_symlink():
            continue
        metadata = path.stat()
        if stat.S_ISREG(metadata.st_mode):
            entries.append(FileEntry(path.name, metadata.st_size))
    entries.sort(key=lambda entry: entry.filename)
    return tuple(entries)


def _listing_error(
    code: ErrorCode,
    message: str,
    session: ServerSession,
) -> Frame:
    return make_error_frame(
        ErrorMessage(Opcode.FILE_LIST, code, message),
        max_payload_bytes=session.config.network.max_payload_bytes,
    )
