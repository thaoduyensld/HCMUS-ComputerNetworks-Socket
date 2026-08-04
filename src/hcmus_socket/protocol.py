"""Protocol v1 constants and data types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


MAGIC = 0x48434D55  # ASCII: HCMU
VERSION = 1
USER_ID = 0  # Phase 1 does not support authenticated users.

MAGIC_SIZE_BYTES = 4
VERSION_SIZE_BYTES = 2
RESERVED_SIZE_BYTES = 2
PREFACE_SIZE_BYTES = (
    MAGIC_SIZE_BYTES + VERSION_SIZE_BYTES + RESERVED_SIZE_BYTES
)

LENGTH_SIZE_BYTES = 4
OPCODE_SIZE_BYTES = 2
USER_ID_SIZE_BYTES = 2
FRAME_BODY_HEADER_SIZE_BYTES = OPCODE_SIZE_BYTES + USER_ID_SIZE_BYTES
FRAME_HEADER_SIZE_BYTES = LENGTH_SIZE_BYTES + FRAME_BODY_HEADER_SIZE_BYTES

MAX_PAYLOAD_BYTES = 1024 * 1024

MIN_CHUNK_SIZE_BYTES = 4 * 1024
CHUNK_SIZE_BYTES = 32 * 1024
MAX_CHUNK_SIZE_BYTES = 64 * 1024
CHUNK_OFFSET_SIZE_BYTES = 8


class Opcode(IntEnum):
    """Message types defined by protocol v1."""

    DISCONNECT = 0x0002

    FILE_LIST = 0x0010
    FILE_LIST_RESP = 0x0011
    FILE_UPLOAD = 0x0012
    FILE_DOWNLOAD = 0x0013
    FILE_CHUNK = 0x0014
    FILE_DELETE = 0x0015  # Reserved for Phase 2.
    FILE_INFO = 0x0016
    FILE_CHECKSUM = 0x0017

    ACK = 0x0020
    ERROR = 0x00FF


class ErrorCode(IntEnum):
    """Error codes carried by ERROR frames."""

    INVALID_FRAME = 0x0001
    UNSUPPORTED_OPCODE = 0x0002
    INVALID_PAYLOAD = 0x0003
    INVALID_STATE = 0x0004
    PAYLOAD_TOO_LARGE = 0x0005
    INVALID_USER_ID = 0x0006

    FILE_NOT_FOUND = 0x0010
    FILE_EXISTS = 0x0011
    INVALID_FILENAME = 0x0012
    ACCESS_DENIED = 0x0013
    FILE_IO_ERROR = 0x0014
    SIZE_MISMATCH = 0x0015
    CHECKSUM_MISMATCH = 0x0016
    OFFSET_MISMATCH = 0x0017
    TRANSFER_IN_PROGRESS = 0x0018
    LIST_TOO_LARGE = 0x0019

    INTERNAL_ERROR = 0x00FF


class ProtocolError(Exception):
    """Raised when data violates protocol v1."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Frame:
    """A decoded protocol frame."""

    opcode: Opcode
    payload: bytes = b""
    user_id: int = USER_ID

    def __post_init__(self) -> None:
        if self.user_id != USER_ID:
            raise ProtocolError(
                ErrorCode.INVALID_USER_ID,
                f"Phase 1 USER_ID must be {USER_ID}, got {self.user_id}",
            )

        if len(self.payload) > MAX_PAYLOAD_BYTES:
            raise ProtocolError(
                ErrorCode.PAYLOAD_TOO_LARGE,
                (
                    f"Payload contains {len(self.payload)} bytes; "
                    f"maximum is {MAX_PAYLOAD_BYTES}"
                ),
            )