from __future__ import annotations

import struct
from collections.abc import Callable

import pytest

from hcmus_socket.messages import (
    Acknowledgement,
    ErrorMessage,
    FileChecksum,
    FileChunk,
    FileDownload,
    FileEntry,
    FileInfo,
    FileListResponse,
    FileUpload,
    make_acknowledgement_frame,
    make_disconnect_frame,
    make_error_frame,
    make_file_checksum_frame,
    make_file_chunk_frame,
    make_file_download_frame,
    make_file_info_frame,
    make_file_list_frame,
    make_file_list_response_frame,
    make_file_upload_frame,
    parse_acknowledgement,
    parse_disconnect,
    parse_error,
    parse_file_checksum,
    parse_file_chunk,
    parse_file_download,
    parse_file_info,
    parse_file_list,
    parse_file_list_response,
    parse_file_upload,
    validate_message,
)
from hcmus_socket.protocol import ErrorCode, Frame, Opcode, ProtocolError


UINT64_MAX = (1 << 64) - 1


def assert_error(code: ErrorCode, function: Callable[[], object]) -> None:
    with pytest.raises(ProtocolError) as raised:
        function()
    assert raised.value.code is code


@pytest.mark.parametrize(
    ("make_frame", "parse_frame"),
    [
        (make_disconnect_frame, parse_disconnect),
        (make_file_list_frame, parse_file_list),
    ],
)
def test_empty_messages_round_trip(
    make_frame: Callable[[], Frame],
    parse_frame: Callable[[Frame], None],
) -> None:
    frame = make_frame()

    assert frame.payload == b""
    assert parse_frame(frame) is None


@pytest.mark.parametrize(
    ("message", "make_frame", "parse_frame"),
    [
        (
            FileListResponse(
                (
                    FileEntry("zero.bin", 0),
                    FileEntry("dữ-liệu.bin", UINT64_MAX),
                )
            ),
            make_file_list_response_frame,
            parse_file_list_response,
        ),
        (FileUpload("dữ-liệu.bin", UINT64_MAX), make_file_upload_frame, parse_file_upload),
        (FileDownload("dữ-liệu.bin"), make_file_download_frame, parse_file_download),
        (FileInfo("empty.bin", 0), make_file_info_frame, parse_file_info),
        (FileChunk(UINT64_MAX, b"\x00\xffdata"), make_file_chunk_frame, parse_file_chunk),
        (
            FileChecksum(UINT64_MAX, bytes(range(32))),
            make_file_checksum_frame,
            parse_file_checksum,
        ),
        (
            Acknowledgement(Opcode.FILE_CHECKSUM, UINT64_MAX),
            make_acknowledgement_frame,
            parse_acknowledgement,
        ),
        (
            ErrorMessage(Opcode.FILE_UPLOAD, ErrorCode.FILE_EXISTS, "Đã tồn tại"),
            make_error_frame,
            parse_error,
        ),
    ],
)
def test_structured_messages_round_trip(
    message: object,
    make_frame: Callable[[object], Frame],
    parse_frame: Callable[[Frame], object],
) -> None:
    assert parse_frame(make_frame(message)) == message


def test_filename_length_uses_utf8_bytes() -> None:
    frame = make_file_download_frame(FileDownload("tệp.bin"))

    (encoded_size,) = struct.unpack("!H", frame.payload[:2])

    assert encoded_size == len("tệp.bin".encode("utf-8"))
    assert encoded_size > len("tệp.bin")


@pytest.mark.parametrize(
    "filename",
    ["", ".", "..", "a/b", "a\\b", "nul\x00name", "é" * 128],
)
def test_invalid_filenames_are_rejected(filename: str) -> None:
    assert_error(
        ErrorCode.INVALID_FILENAME,
        lambda: make_file_upload_frame(FileUpload(filename, 1)),
    )


@pytest.mark.parametrize(
    ("make_valid", "parser"),
    [
        (
            lambda: make_file_list_response_frame(
                FileListResponse((FileEntry("a", 1),))
            ),
            parse_file_list_response,
        ),
        (lambda: make_file_upload_frame(FileUpload("a", 1)), parse_file_upload),
        (lambda: make_file_download_frame(FileDownload("a")), parse_file_download),
        (lambda: make_file_info_frame(FileInfo("a", 1)), parse_file_info),
        (
            lambda: make_error_frame(
                ErrorMessage(Opcode.FILE_LIST, ErrorCode.INVALID_PAYLOAD, "bad")
            ),
            parse_error,
        ),
    ],
)
def test_variable_messages_reject_truncation_and_trailing_bytes(
    make_valid: Callable[[], Frame],
    parser: Callable[[Frame], object],
) -> None:
    valid = make_valid()

    for size in range(len(valid.payload)):
        assert_error(
            ErrorCode.INVALID_PAYLOAD,
            lambda size=size: parser(Frame(valid.opcode, valid.payload[:size])),
        )
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: parser(Frame(valid.opcode, valid.payload + b"x")),
    )


@pytest.mark.parametrize(
    ("opcode", "payload", "parser"),
    [
        (Opcode.FILE_UPLOAD, b"\x00\x01\xff" + bytes(16), parse_file_upload),
        (Opcode.FILE_DOWNLOAD, b"\x00\x01\xff" + bytes(8), parse_file_download),
        (
            Opcode.FILE_LIST_RESP,
            b"\x00\x00\x00\x01\x00\x01\xff" + bytes(8),
            parse_file_list_response,
        ),
    ],
)
def test_invalid_filename_utf8_is_rejected(
    opcode: Opcode,
    payload: bytes,
    parser: Callable[[Frame], object],
) -> None:
    assert_error(
        ErrorCode.INVALID_FILENAME,
        lambda: parser(Frame(opcode, payload)),
    )


@pytest.mark.parametrize(
    ("frame", "parser"),
    [
        (
            Frame(Opcode.FILE_UPLOAD, b"\x00\x01a" + struct.pack("!QQ", 1, 1)),
            parse_file_upload,
        ),
        (
            Frame(Opcode.FILE_DOWNLOAD, b"\x00\x01a" + struct.pack("!Q", 1)),
            parse_file_download,
        ),
        (
            Frame(Opcode.FILE_INFO, b"\x00\x01a" + struct.pack("!QQ", 1, 1)),
            parse_file_info,
        ),
    ],
)
def test_phase_one_offsets_must_be_zero(
    frame: Frame,
    parser: Callable[[Frame], object],
) -> None:
    assert_error(ErrorCode.INVALID_PAYLOAD, lambda: parser(frame))


def test_file_chunk_rejects_empty_or_oversized_data() -> None:
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: make_file_chunk_frame(FileChunk(0, b"")),
    )
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: make_file_chunk_frame(FileChunk(0, b"12345"), chunk_size_bytes=4),
    )
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: parse_file_chunk(
            Frame(Opcode.FILE_CHUNK, struct.pack("!Q", 0) + b"12345"),
            chunk_size_bytes=4,
        ),
    )


@pytest.mark.parametrize("payload_size", [39, 41])
def test_file_checksum_requires_exact_payload_size(payload_size: int) -> None:
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: parse_file_checksum(Frame(Opcode.FILE_CHECKSUM, bytes(payload_size))),
    )


def test_file_checksum_rejects_hex_digest() -> None:
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: make_file_checksum_frame(  # type: ignore[arg-type]
            FileChecksum(1, "00" * 32)
        ),
    )


@pytest.mark.parametrize("payload_size", [0, 9, 11])
def test_acknowledgement_requires_exact_payload_size(payload_size: int) -> None:
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: parse_acknowledgement(Frame(Opcode.ACK, bytes(payload_size))),
    )


def test_error_rejects_mismatched_length_and_invalid_utf8() -> None:
    header = struct.pack(
        "!HHH",
        Opcode.FILE_LIST,
        ErrorCode.INVALID_PAYLOAD,
        2,
    )
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: parse_error(Frame(Opcode.ERROR, header + b"x")),
    )
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: parse_error(Frame(Opcode.ERROR, header + b"\xff\xff")),
    )


def test_error_rejects_message_over_uint16() -> None:
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: make_error_frame(
            ErrorMessage(Opcode.FILE_LIST, ErrorCode.INVALID_PAYLOAD, "a" * 65536)
        ),
    )


def test_parser_rejects_wrong_opcode() -> None:
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: parse_file_list(make_disconnect_frame()),
    )


def test_phase_one_rejects_file_delete() -> None:
    assert_error(
        ErrorCode.UNSUPPORTED_OPCODE,
        lambda: validate_message(Frame(Opcode.FILE_DELETE)),
    )


def test_configured_payload_limit_is_enforced() -> None:
    response = FileListResponse((FileEntry("abc", 1),))
    frame = make_file_list_response_frame(response)

    assert_error(
        ErrorCode.PAYLOAD_TOO_LARGE,
        lambda: make_file_list_response_frame(response, max_payload_bytes=4),
    )
    assert_error(
        ErrorCode.PAYLOAD_TOO_LARGE,
        lambda: parse_file_list_response(frame, max_payload_bytes=4),
    )


@pytest.mark.parametrize("value", [-1, UINT64_MAX + 1])
def test_out_of_range_uint64_is_rejected(value: int) -> None:
    assert_error(
        ErrorCode.INVALID_PAYLOAD,
        lambda: make_file_info_frame(FileInfo("a", value)),
    )
