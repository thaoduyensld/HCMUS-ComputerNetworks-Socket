"""TCP framing helpers for HCMUS Socket Protocol v1."""

from __future__ import annotations

import socket
import struct

from .protocol import (
    FRAME_BODY_HEADER_SIZE_BYTES,
    FRAME_HEADER_SIZE_BYTES,
    LENGTH_SIZE_BYTES,
    MAGIC,
    MAX_PAYLOAD_BYTES,
    PREFACE_SIZE_BYTES,
    USER_ID,
    VERSION,
    ErrorCode,
    Frame,
    Opcode,
    ProtocolError,
)


PREFACE_STRUCT = struct.Struct("!IHH")
FRAME_HEADER_STRUCT = struct.Struct("!IHH")
LENGTH_STRUCT = struct.Struct("!I")


def send_all(sock: socket.socket, data: bytes) -> None:
    """Send every byte in *data*, even when ``send`` writes only a prefix."""

    view = memoryview(data)
    bytes_sent = 0

    while bytes_sent < len(view):
        sent = sock.send(view[bytes_sent:])
        if sent == 0:
            raise ConnectionError("peer closed while sending data")
        bytes_sent += sent


def recv_exact(sock: socket.socket, size: int) -> bytes | None:
    """Receive exactly *size* bytes.

    Return ``None`` when the peer closes before any byte is received. If the
    peer closes after a partial read, the byte stream no longer contains a
    complete protocol unit and ``ProtocolError`` is raised.
    """

    if size < 0:
        raise ValueError("receive size must not be negative")
    if size == 0:
        return b""

    received = bytearray()
    while len(received) < size:
        chunk = sock.recv(size - len(received))
        if not chunk:
            if not received:
                return None
            raise ProtocolError(
                ErrorCode.INVALID_FRAME,
                f"peer closed after {len(received)} of {size} bytes",
            )
        received.extend(chunk)

    return bytes(received)


def encode_preface() -> bytes:
    """Encode the fixed eight-byte protocol v1 connection preface."""

    return PREFACE_STRUCT.pack(MAGIC, VERSION, 0)


def decode_preface(data: bytes) -> tuple[int, int, int]:
    """Decode preface bytes into ``(magic, version, reserved)``."""

    if len(data) != PREFACE_SIZE_BYTES:
        raise ProtocolError(
            ErrorCode.INVALID_FRAME,
            f"preface must contain {PREFACE_SIZE_BYTES} bytes, got {len(data)}",
        )
    return PREFACE_STRUCT.unpack(data)


def validate_preface(preface: tuple[int, int, int]) -> None:
    """Reject a preface that is incompatible with protocol v1."""

    magic, version, reserved = preface
    if magic != MAGIC:
        raise ProtocolError(ErrorCode.INVALID_FRAME, "invalid preface MAGIC")
    if version != VERSION:
        raise ProtocolError(
            ErrorCode.INVALID_FRAME,
            f"unsupported protocol version {version}",
        )
    if reserved != 0:
        raise ProtocolError(ErrorCode.INVALID_FRAME, "preface RESERVED must be zero")


def serialize_frame(frame: Frame) -> bytes:
    """Serialize a validated frame using network byte order."""

    payload_size = len(frame.payload)
    if payload_size > MAX_PAYLOAD_BYTES:
        raise ProtocolError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"payload contains {payload_size} bytes; maximum is {MAX_PAYLOAD_BYTES}",
        )
    if frame.user_id != USER_ID:
        raise ProtocolError(
            ErrorCode.INVALID_USER_ID,
            f"Phase 1 USER_ID must be {USER_ID}, got {frame.user_id}",
        )

    length = FRAME_BODY_HEADER_SIZE_BYTES + payload_size
    header = FRAME_HEADER_STRUCT.pack(length, int(frame.opcode), frame.user_id)
    return header + frame.payload


def receive_frame(
    sock: socket.socket,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> Frame | None:
    """Receive and validate one frame, preserving subsequent stream bytes."""

    length_bytes = recv_exact(sock, LENGTH_SIZE_BYTES)
    if length_bytes is None:
        return None

    (length,) = LENGTH_STRUCT.unpack(length_bytes)
    if length < FRAME_BODY_HEADER_SIZE_BYTES:
        raise ProtocolError(
            ErrorCode.INVALID_FRAME,
            f"frame LENGTH must be at least {FRAME_BODY_HEADER_SIZE_BYTES}, got {length}",
        )

    payload_size = length - FRAME_BODY_HEADER_SIZE_BYTES
    if payload_size > max_payload_bytes:
        raise ProtocolError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"payload contains {payload_size} bytes; maximum is {max_payload_bytes}",
        )

    body_header = recv_exact(sock, FRAME_BODY_HEADER_SIZE_BYTES)
    if body_header is None:
        raise ProtocolError(
            ErrorCode.INVALID_FRAME,
            "peer closed after LENGTH and before OPCODE/USER_ID",
        )

    _, raw_opcode, user_id = FRAME_HEADER_STRUCT.unpack(length_bytes + body_header)
    if user_id != USER_ID:
        raise ProtocolError(
            ErrorCode.INVALID_USER_ID,
            f"Phase 1 USER_ID must be {USER_ID}, got {user_id}",
        )

    try:
        opcode = Opcode(raw_opcode)
    except ValueError as error:
        raise ProtocolError(
            ErrorCode.UNSUPPORTED_OPCODE,
            f"unsupported opcode 0x{raw_opcode:04X}",
        ) from error

    payload = recv_exact(sock, payload_size)
    if payload is None:
        raise ProtocolError(
            ErrorCode.INVALID_FRAME,
            f"peer closed before the {payload_size}-byte payload",
        )

    return Frame(opcode=opcode, payload=payload, user_id=user_id)
