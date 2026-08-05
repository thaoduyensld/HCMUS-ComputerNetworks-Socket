import pytest

from hcmus_socket.protocol import (
    CHUNK_OFFSET_SIZE_BYTES,
    CHUNK_SIZE_BYTES,
    FRAME_HEADER_SIZE_BYTES,
    MAGIC,
    MAX_CHUNK_SIZE_BYTES,
    MAX_PAYLOAD_BYTES,
    MIN_CHUNK_SIZE_BYTES,
    PREFACE_SIZE_BYTES,
    USER_ID,
    VERSION,
    ErrorCode,
    Frame,
    Opcode,
    ProtocolError,
)


def test_protocol_v1_constants() -> None:
    assert MAGIC == 0x48434D55
    assert VERSION == 1
    assert PREFACE_SIZE_BYTES == 8
    assert FRAME_HEADER_SIZE_BYTES == 8


@pytest.mark.parametrize(
    ("opcode", "expected"),
    [
        (Opcode.DISCONNECT, 0x0002),
        (Opcode.FILE_LIST, 0x0010),
        (Opcode.FILE_LIST_RESP, 0x0011),
        (Opcode.FILE_UPLOAD, 0x0012),
        (Opcode.FILE_DOWNLOAD, 0x0013),
        (Opcode.FILE_CHUNK, 0x0014),
        (Opcode.FILE_DELETE, 0x0015),
        (Opcode.FILE_INFO, 0x0016),
        (Opcode.FILE_CHECKSUM, 0x0017),
        (Opcode.ACK, 0x0020),
        (Opcode.ERROR, 0x00FF),
    ],
)
def test_opcode_values_match_protocol(
    opcode: Opcode,
    expected: int,
) -> None:
    assert int(opcode) == expected


def test_phase_one_frame_uses_user_id_zero() -> None:
    frame = Frame(opcode=Opcode.FILE_LIST)

    assert USER_ID == 0
    assert frame.user_id == 0


def test_phase_one_rejects_nonzero_user_id() -> None:
    with pytest.raises(ProtocolError) as raised:
        Frame(opcode=Opcode.FILE_LIST, user_id=1)

    assert raised.value.code is ErrorCode.INVALID_USER_ID


def test_payload_and_chunk_limits_are_valid() -> None:
    assert MAX_PAYLOAD_BYTES == 1024 * 1024
    assert CHUNK_SIZE_BYTES == 32 * 1024

    assert MIN_CHUNK_SIZE_BYTES <= CHUNK_SIZE_BYTES
    assert CHUNK_SIZE_BYTES <= MAX_CHUNK_SIZE_BYTES
    assert CHUNK_OFFSET_SIZE_BYTES + CHUNK_SIZE_BYTES <= MAX_PAYLOAD_BYTES


def test_frame_rejects_payload_over_limit() -> None:
    oversized_payload = bytes(MAX_PAYLOAD_BYTES + 1)

    with pytest.raises(ProtocolError) as raised:
        Frame(opcode=Opcode.FILE_CHUNK, payload=oversized_payload)

    assert raised.value.code is ErrorCode.PAYLOAD_TOO_LARGE


def test_frame_accepts_payload_with_larger_configured_limit() -> None:
    payload = bytes(MAX_PAYLOAD_BYTES + 1)

    frame = Frame(
        opcode=Opcode.FILE_LIST_RESP,
        payload=payload,
        max_payload_bytes=len(payload),
    )

    assert frame.payload == payload
