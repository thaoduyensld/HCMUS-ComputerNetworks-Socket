"""Client-side FILE_LIST request and response handling."""

from __future__ import annotations

from ..messages import (
    FileListResponse,
    make_file_list_frame,
    parse_error,
    parse_file_list_response,
)
from ..protocol import USER_ID, ErrorCode, Opcode, ProtocolError
from .session import ClientSession


def list_files(session: ClientSession) -> FileListResponse:
    """Request the server's public files while preserving the open session."""

    maximum = session.config.network.max_payload_bytes
    session.send(
        make_file_list_frame(
            maximum,
            user_id=getattr(session, "user_id", USER_ID),
        )
    )
    frame = session.receive()

    if frame.opcode is Opcode.ERROR:
        error = parse_error(frame, maximum)
        if error.failed_opcode is not Opcode.FILE_LIST:
            raise ProtocolError(
                ErrorCode.INVALID_STATE,
                f"server returned ERROR for {error.failed_opcode.name} during LIST",
            )
        raise ProtocolError(error.error_code, f"server: {error.message}")

    if frame.opcode is not Opcode.FILE_LIST_RESP:
        raise ProtocolError(
            ErrorCode.INVALID_STATE,
            f"expected FILE_LIST_RESP, got {frame.opcode.name}",
        )

    response = parse_file_list_response(frame, maximum)
    return FileListResponse(
        tuple(sorted(response.entries, key=lambda entry: entry.filename))
    )
