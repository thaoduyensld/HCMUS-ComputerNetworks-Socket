from __future__ import annotations

from collections import deque

import pytest

from hcmus_socket.framing import (
    FRAME_HEADER_STRUCT,
    decode_preface,
    encode_preface,
    receive_frame,
    recv_exact,
    send_all,
    send_frame,
    serialize_frame,
    validate_preface,
)
from hcmus_socket.protocol import (
    FRAME_BODY_HEADER_SIZE_BYTES,
    MAGIC,
    MAX_PAYLOAD_BYTES,
    USER_ID,
    VERSION,
    ErrorCode,
    Frame,
    Opcode,
    ProtocolError,
)


class BufferedSocket:
    """Small socket double whose recv boundaries are controlled by the test."""

    def __init__(self, *chunks: bytes) -> None:
        self.chunks = deque(bytearray(chunk) for chunk in chunks)

    def recv(self, size: int) -> bytes:
        if not self.chunks:
            return b""

        chunk = self.chunks[0]
        result = bytes(chunk[:size])
        del chunk[:size]
        if not chunk:
            self.chunks.popleft()
        return result


class PartialSendSocket:
    """Socket double that accepts at most two bytes per send call."""

    def __init__(self) -> None:
        self.data = bytearray()

    def send(self, data: memoryview) -> int:
        accepted = min(2, len(data))
        self.data.extend(data[:accepted])
        return accepted


def assert_protocol_error(
    expected_code: ErrorCode,
    function: object,
) -> None:
    with pytest.raises(ProtocolError) as raised:
        function()  # type: ignore[operator]
    assert raised.value.code is expected_code


def test_send_all_handles_partial_writes() -> None:
    sock = PartialSendSocket()

    send_all(sock, b"abcdefgh")  # type: ignore[arg-type]

    assert bytes(sock.data) == b"abcdefgh"


def test_send_frame_handles_partial_writes() -> None:
    frame = Frame(Opcode.ERROR, b"partial payload")
    sock = PartialSendSocket()

    send_frame(sock, frame)  # type: ignore[arg-type]

    assert bytes(sock.data) == serialize_frame(frame)


def test_send_frame_honors_configured_payload_limit() -> None:
    frame = Frame(Opcode.ERROR, b"12345")

    assert_protocol_error(
        ErrorCode.PAYLOAD_TOO_LARGE,
        lambda: send_frame(  # type: ignore[arg-type]
            PartialSendSocket(),
            frame,
            max_payload_bytes=4,
        ),
    )


def test_recv_exact_handles_partial_reads() -> None:
    sock = BufferedSocket(b"a", b"bc", b"def")

    assert recv_exact(sock, 6) == b"abcdef"  # type: ignore[arg-type]


def test_preface_round_trip() -> None:
    encoded = encode_preface()
    decoded = decode_preface(encoded)

    validate_preface(decoded)
    assert decoded == (MAGIC, VERSION, 0)


@pytest.mark.parametrize(
    "preface",
    [
        (0, VERSION, 0),
        (MAGIC, VERSION + 1, 0),
        (MAGIC, VERSION, 1),
    ],
)
def test_invalid_preface_is_rejected(preface: tuple[int, int, int]) -> None:
    assert_protocol_error(
        ErrorCode.INVALID_FRAME,
        lambda: validate_preface(preface),
    )


def test_decode_preface_rejects_wrong_size() -> None:
    assert_protocol_error(
        ErrorCode.INVALID_FRAME,
        lambda: decode_preface(b"too short"),
    )


def test_frame_round_trip() -> None:
    original = Frame(Opcode.FILE_CHUNK, b"\x00binary\xffpayload")
    sock = BufferedSocket(serialize_frame(original))

    decoded = receive_frame(sock)  # type: ignore[arg-type]

    assert decoded == original


def test_length_below_four_is_rejected() -> None:
    header = FRAME_HEADER_STRUCT.pack(3, Opcode.FILE_LIST, USER_ID)

    assert_protocol_error(
        ErrorCode.INVALID_FRAME,
        lambda: receive_frame(BufferedSocket(header)),  # type: ignore[arg-type]
    )


def test_oversized_payload_is_rejected_before_reading_payload() -> None:
    length = FRAME_BODY_HEADER_SIZE_BYTES + MAX_PAYLOAD_BYTES + 1
    header = FRAME_HEADER_STRUCT.pack(length, Opcode.FILE_CHUNK, USER_ID)

    assert_protocol_error(
        ErrorCode.PAYLOAD_TOO_LARGE,
        lambda: receive_frame(BufferedSocket(header)),  # type: ignore[arg-type]
    )


def test_nonzero_user_id_is_rejected() -> None:
    header = FRAME_HEADER_STRUCT.pack(
        FRAME_BODY_HEADER_SIZE_BYTES,
        Opcode.FILE_LIST,
        1,
    )

    assert_protocol_error(
        ErrorCode.INVALID_USER_ID,
        lambda: receive_frame(BufferedSocket(header)),  # type: ignore[arg-type]
    )


def test_unknown_opcode_is_rejected() -> None:
    header = FRAME_HEADER_STRUCT.pack(
        FRAME_BODY_HEADER_SIZE_BYTES,
        0x7777,
        USER_ID,
    )

    assert_protocol_error(
        ErrorCode.UNSUPPORTED_OPCODE,
        lambda: receive_frame(BufferedSocket(header)),  # type: ignore[arg-type]
    )


def test_split_header_and_payload_are_received() -> None:
    original = Frame(Opcode.ERROR, b"split payload")
    encoded = serialize_frame(original)
    sock = BufferedSocket(encoded[:2], encoded[2:7], encoded[7:10], encoded[10:])

    assert receive_frame(sock) == original  # type: ignore[arg-type]


def test_consecutive_frames_remain_separate() -> None:
    first = Frame(Opcode.FILE_LIST)
    second = Frame(Opcode.DISCONNECT)
    sock = BufferedSocket(serialize_frame(first) + serialize_frame(second))

    assert receive_frame(sock) == first  # type: ignore[arg-type]
    assert receive_frame(sock) == second  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "partial_frame",
    [
        b"\x00\x00",
        FRAME_HEADER_STRUCT.pack(4, Opcode.FILE_LIST, USER_ID)[:4],
        FRAME_HEADER_STRUCT.pack(12, Opcode.FILE_CHUNK, USER_ID) + b"part",
    ],
)
def test_peer_close_mid_frame_is_rejected(partial_frame: bytes) -> None:
    assert_protocol_error(
        ErrorCode.INVALID_FRAME,
        lambda: receive_frame(BufferedSocket(partial_frame)),  # type: ignore[arg-type]
    )


def test_clean_peer_close_before_frame_returns_none() -> None:
    assert receive_frame(BufferedSocket()) is None  # type: ignore[arg-type]
