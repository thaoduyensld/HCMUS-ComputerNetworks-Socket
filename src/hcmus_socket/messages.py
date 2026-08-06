"""Protocol v2 message models and payload codecs."""

from __future__ import annotations

from dataclasses import dataclass
import re
import struct
from typing import Callable

from .protocol import (
    CHUNK_SIZE_BYTES,
    MAX_FILENAME_BYTES,
    MAX_PAYLOAD_BYTES,
    MAX_USERNAME_BYTES,
    SHA256_DIGEST_SIZE_BYTES,
    USER_ID,
    ErrorCode,
    Frame,
    Opcode,
    ProtocolError,
)


UINT16_MAX = (1 << 16) - 1
UINT32_MAX = (1 << 32) - 1
UINT64_MAX = (1 << 64) - 1

UINT16 = struct.Struct("!H")
UINT32 = struct.Struct("!I")
UINT64 = struct.Struct("!Q")
UPLOAD_INFO_SUFFIX = struct.Struct("!QQ")
ACK_PAYLOAD = struct.Struct("!HQ")
ERROR_HEADER = struct.Struct("!HHH")
USERNAME_PATTERN = re.compile(rb"[A-Za-z0-9_-]+\Z")


@dataclass(frozen=True, slots=True)
class LoginRequest:
    username: str


@dataclass(frozen=True, slots=True)
class FileEntry:
    filename: str
    file_size: int


@dataclass(frozen=True, slots=True)
class FileListResponse:
    entries: tuple[FileEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))


@dataclass(frozen=True, slots=True)
class FileUpload:
    filename: str
    total_size: int
    start_offset: int = 0


@dataclass(frozen=True, slots=True)
class FileDownload:
    filename: str
    requested_offset: int = 0


@dataclass(frozen=True, slots=True)
class FileInfo:
    filename: str
    total_size: int
    start_offset: int = 0


@dataclass(frozen=True, slots=True)
class FileChunk:
    offset: int
    data: bytes


@dataclass(frozen=True, slots=True)
class FileChecksum:
    final_size: int
    sha256_digest: bytes


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    acknowledged_opcode: Opcode
    next_offset: int


@dataclass(frozen=True, slots=True)
class ErrorMessage:
    failed_opcode: Opcode | int
    error_code: ErrorCode
    message: str


class _PayloadReader:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def read(self, size: int, field: str) -> bytes:
        end = self._offset + size
        if end > len(self._payload):
            raise ProtocolError(
                ErrorCode.INVALID_PAYLOAD,
                f"payload is truncated while reading {field}",
            )
        value = self._payload[self._offset:end]
        self._offset = end
        return value

    def uint16(self, field: str) -> int:
        return UINT16.unpack(self.read(UINT16.size, field))[0]

    def uint32(self, field: str) -> int:
        return UINT32.unpack(self.read(UINT32.size, field))[0]

    def uint64(self, field: str) -> int:
        return UINT64.unpack(self.read(UINT64.size, field))[0]

    def remaining(self) -> bytes:
        value = self._payload[self._offset :]
        self._offset = len(self._payload)
        return value

    def finish(self) -> None:
        if self._offset != len(self._payload):
            raise ProtocolError(
                ErrorCode.INVALID_PAYLOAD,
                f"payload has {len(self._payload) - self._offset} trailing bytes",
            )


def _validate_uint(value: int, maximum: int, field: str) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"{field} must be an integer from 0 to {maximum}",
        )


def _validate_payload_size(payload: bytes, max_payload_bytes: int) -> None:
    if len(payload) > max_payload_bytes:
        raise ProtocolError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"payload contains {len(payload)} bytes; maximum is {max_payload_bytes}",
        )


def _validate_frame(
    frame: Frame,
    opcode: Opcode,
    max_payload_bytes: int,
) -> None:
    if frame.opcode != opcode:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"expected {opcode.name} frame, got {frame.opcode!r}",
        )
    _validate_payload_size(frame.payload, max_payload_bytes)


def _encode_username(username: str) -> bytes:
    if not isinstance(username, str):
        raise ProtocolError(ErrorCode.INVALID_USERNAME, "username must be text")
    try:
        encoded = username.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ProtocolError(
            ErrorCode.INVALID_USERNAME,
            "username is not valid UTF-8 text",
        ) from error
    if not 1 <= len(encoded) <= MAX_USERNAME_BYTES:
        raise ProtocolError(
            ErrorCode.INVALID_USERNAME,
            f"username must contain 1 to {MAX_USERNAME_BYTES} UTF-8 bytes",
        )
    if USERNAME_PATTERN.fullmatch(encoded) is None:
        raise ProtocolError(
            ErrorCode.INVALID_USERNAME,
            "username may contain only A-Z, a-z, 0-9, underscore, and hyphen",
        )
    return encoded


def _decode_username(reader: _PayloadReader) -> str:
    size = reader.uint16("username_length")
    encoded = reader.read(size, "username")
    reader.finish()
    try:
        username = encoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ProtocolError(
            ErrorCode.INVALID_USERNAME,
            "username is not valid UTF-8",
        ) from error
    _encode_username(username)
    return username


def _encode_filename(filename: str) -> bytes:
    if not isinstance(filename, str):
        raise ProtocolError(ErrorCode.INVALID_FILENAME, "filename must be text")
    try:
        encoded = filename.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ProtocolError(
            ErrorCode.INVALID_FILENAME,
            "filename is not valid UTF-8 text",
        ) from error

    if not encoded:
        raise ProtocolError(ErrorCode.INVALID_FILENAME, "filename must not be empty")
    if len(encoded) > MAX_FILENAME_BYTES:
        raise ProtocolError(
            ErrorCode.INVALID_FILENAME,
            f"filename exceeds {MAX_FILENAME_BYTES} UTF-8 bytes",
        )
    if filename in {".", ".."}:
        raise ProtocolError(
            ErrorCode.INVALID_FILENAME,
            "filename must not be a directory traversal component",
        )
    if "\x00" in filename:
        raise ProtocolError(ErrorCode.INVALID_FILENAME, "filename contains NUL")
    if "/" in filename or "\\" in filename:
        raise ProtocolError(
            ErrorCode.INVALID_FILENAME,
            "filename must be a basename without path separators",
        )
    return encoded


def _decode_filename(reader: _PayloadReader) -> str:
    size = reader.uint16("filename_length")
    encoded = reader.read(size, "filename")
    try:
        filename = encoded.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProtocolError(
            ErrorCode.INVALID_FILENAME,
            "filename is not valid UTF-8",
        ) from error
    _encode_filename(filename)
    return filename


def _filename_payload(filename: str) -> bytes:
    encoded = _encode_filename(filename)
    return UINT16.pack(len(encoded)) + encoded


def _make_frame(
    opcode: Opcode,
    payload: bytes,
    max_payload_bytes: int,
    user_id: int = USER_ID,
) -> Frame:
    _validate_payload_size(payload, max_payload_bytes)
    return Frame(
        opcode,
        payload,
        user_id=user_id,
        max_payload_bytes=max_payload_bytes,
    )


def make_login_frame(
    message: LoginRequest,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    if user_id != USER_ID:
        raise ProtocolError(
            ErrorCode.INVALID_USER_ID,
            "LOGIN frame USER_ID must be zero",
        )
    encoded = _encode_username(message.username)
    return _make_frame(
        Opcode.LOGIN,
        UINT16.pack(len(encoded)) + encoded,
        max_payload_bytes,
        user_id,
    )


def parse_login(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> LoginRequest:
    _validate_frame(frame, Opcode.LOGIN, max_payload_bytes)
    if frame.user_id != USER_ID:
        raise ProtocolError(
            ErrorCode.INVALID_USER_ID,
            "LOGIN frame USER_ID must be zero",
        )
    return LoginRequest(_decode_username(_PayloadReader(frame.payload)))


def make_disconnect_frame(
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    return _make_frame(Opcode.DISCONNECT, b"", max_payload_bytes, user_id)


def parse_disconnect(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> None:
    _parse_empty(frame, Opcode.DISCONNECT, max_payload_bytes)


def make_file_list_frame(
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    return _make_frame(Opcode.FILE_LIST, b"", max_payload_bytes, user_id)


def parse_file_list(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> None:
    _parse_empty(frame, Opcode.FILE_LIST, max_payload_bytes)


def _parse_empty(
    frame: Frame,
    opcode: Opcode,
    max_payload_bytes: int,
) -> None:
    _validate_frame(frame, opcode, max_payload_bytes)
    if frame.payload:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"{opcode.name} payload must be empty",
        )


def make_file_list_response_frame(
    message: FileListResponse,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    entries = tuple(message.entries)
    _validate_uint(len(entries), UINT32_MAX, "file_count")
    parts = [UINT32.pack(len(entries))]
    for entry in entries:
        _validate_uint(entry.file_size, UINT64_MAX, "file_size")
        parts.append(_filename_payload(entry.filename))
        parts.append(UINT64.pack(entry.file_size))
    return _make_frame(
        Opcode.FILE_LIST_RESP,
        b"".join(parts),
        max_payload_bytes,
        user_id,
    )


def parse_file_list_response(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> FileListResponse:
    _validate_frame(frame, Opcode.FILE_LIST_RESP, max_payload_bytes)
    reader = _PayloadReader(frame.payload)
    count = reader.uint32("file_count")
    entries: list[FileEntry] = []
    for _ in range(count):
        filename = _decode_filename(reader)
        entries.append(FileEntry(filename, reader.uint64("file_size")))
    reader.finish()
    return FileListResponse(tuple(entries))


def make_file_upload_frame(
    message: FileUpload,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    _validate_uint(message.total_size, UINT64_MAX, "total_size")
    _require_zero(message.start_offset, "start_offset")
    payload = _filename_payload(message.filename) + UPLOAD_INFO_SUFFIX.pack(
        message.total_size,
        message.start_offset,
    )
    return _make_frame(Opcode.FILE_UPLOAD, payload, max_payload_bytes, user_id)


def parse_file_upload(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> FileUpload:
    _validate_frame(frame, Opcode.FILE_UPLOAD, max_payload_bytes)
    reader = _PayloadReader(frame.payload)
    filename = _decode_filename(reader)
    total_size = reader.uint64("total_size")
    start_offset = reader.uint64("start_offset")
    reader.finish()
    _require_zero(start_offset, "start_offset")
    return FileUpload(filename, total_size, start_offset)


def make_file_download_frame(
    message: FileDownload,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    _require_zero(message.requested_offset, "requested_offset")
    payload = _filename_payload(message.filename) + UINT64.pack(
        message.requested_offset
    )
    return _make_frame(Opcode.FILE_DOWNLOAD, payload, max_payload_bytes, user_id)


def parse_file_download(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> FileDownload:
    _validate_frame(frame, Opcode.FILE_DOWNLOAD, max_payload_bytes)
    reader = _PayloadReader(frame.payload)
    filename = _decode_filename(reader)
    requested_offset = reader.uint64("requested_offset")
    reader.finish()
    _require_zero(requested_offset, "requested_offset")
    return FileDownload(filename, requested_offset)


def make_file_info_frame(
    message: FileInfo,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    _validate_uint(message.total_size, UINT64_MAX, "total_size")
    _require_zero(message.start_offset, "start_offset")
    payload = _filename_payload(message.filename) + UPLOAD_INFO_SUFFIX.pack(
        message.total_size,
        message.start_offset,
    )
    return _make_frame(Opcode.FILE_INFO, payload, max_payload_bytes, user_id)


def parse_file_info(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> FileInfo:
    _validate_frame(frame, Opcode.FILE_INFO, max_payload_bytes)
    reader = _PayloadReader(frame.payload)
    filename = _decode_filename(reader)
    total_size = reader.uint64("total_size")
    start_offset = reader.uint64("start_offset")
    reader.finish()
    _require_zero(start_offset, "start_offset")
    return FileInfo(filename, total_size, start_offset)


def _require_zero(value: int, field: str) -> None:
    _validate_uint(value, UINT64_MAX, field)
    if value != 0:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"Phase 1 {field} must be zero",
        )


def make_file_chunk_frame(
    message: FileChunk,
    chunk_size_bytes: int = CHUNK_SIZE_BYTES,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    _validate_uint(message.offset, UINT64_MAX, "offset")
    if not isinstance(message.data, bytes):
        raise ProtocolError(ErrorCode.INVALID_PAYLOAD, "chunk data must be bytes")
    _validate_chunk_data(message.data, chunk_size_bytes)
    return _make_frame(
        Opcode.FILE_CHUNK,
        UINT64.pack(message.offset) + message.data,
        max_payload_bytes,
        user_id,
    )


def parse_file_chunk(
    frame: Frame,
    chunk_size_bytes: int = CHUNK_SIZE_BYTES,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> FileChunk:
    _validate_frame(frame, Opcode.FILE_CHUNK, max_payload_bytes)
    reader = _PayloadReader(frame.payload)
    offset = reader.uint64("offset")
    data = reader.remaining()
    _validate_chunk_data(data, chunk_size_bytes)
    return FileChunk(offset, data)


def _validate_chunk_data(data: bytes, chunk_size_bytes: int) -> None:
    if not data:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            "FILE_CHUNK data must contain at least one byte",
        )
    if len(data) > chunk_size_bytes:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"chunk data contains {len(data)} bytes; maximum is {chunk_size_bytes}",
        )


def make_file_checksum_frame(
    message: FileChecksum,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    _validate_uint(message.final_size, UINT64_MAX, "final_size")
    if (
        not isinstance(message.sha256_digest, bytes)
        or len(message.sha256_digest) != SHA256_DIGEST_SIZE_BYTES
    ):
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"sha256_digest must contain exactly {SHA256_DIGEST_SIZE_BYTES} raw bytes",
        )
    payload = UINT64.pack(message.final_size) + message.sha256_digest
    return _make_frame(Opcode.FILE_CHECKSUM, payload, max_payload_bytes, user_id)


def parse_file_checksum(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> FileChecksum:
    _validate_frame(frame, Opcode.FILE_CHECKSUM, max_payload_bytes)
    expected_size = UINT64.size + SHA256_DIGEST_SIZE_BYTES
    if len(frame.payload) != expected_size:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"FILE_CHECKSUM payload must contain exactly {expected_size} bytes",
        )
    return FileChecksum(
        UINT64.unpack(frame.payload[: UINT64.size])[0],
        frame.payload[UINT64.size :],
    )


def make_acknowledgement_frame(
    message: Acknowledgement,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    _validate_opcode_value(message.acknowledged_opcode, "acknowledged_opcode")
    _validate_uint(message.next_offset, UINT64_MAX, "next_offset")
    payload = ACK_PAYLOAD.pack(
        int(message.acknowledged_opcode),
        message.next_offset,
    )
    return _make_frame(Opcode.ACK, payload, max_payload_bytes, user_id)


def parse_acknowledgement(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> Acknowledgement:
    _validate_frame(frame, Opcode.ACK, max_payload_bytes)
    if len(frame.payload) != ACK_PAYLOAD.size:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"ACK payload must contain exactly {ACK_PAYLOAD.size} bytes",
        )
    raw_opcode, next_offset = ACK_PAYLOAD.unpack(frame.payload)
    return Acknowledgement(
        _decode_opcode(raw_opcode, "acknowledged_opcode"),
        next_offset,
    )


def make_error_frame(
    message: ErrorMessage,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    *,
    user_id: int = USER_ID,
) -> Frame:
    if (
        not isinstance(message.failed_opcode, int)
        or isinstance(message.failed_opcode, bool)
        or not 0 <= message.failed_opcode <= UINT16_MAX
    ):
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"failed_opcode must be an integer from 0 to {UINT16_MAX}",
        )
    if not isinstance(message.error_code, ErrorCode):
        raise ProtocolError(ErrorCode.INVALID_PAYLOAD, "error_code is not defined")
    if not isinstance(message.message, str):
        raise ProtocolError(ErrorCode.INVALID_PAYLOAD, "ERROR message must be text")
    try:
        encoded = message.message.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            "ERROR message is not valid UTF-8 text",
        ) from error
    if len(encoded) > UINT16_MAX:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            "ERROR message exceeds uint16 message_length",
        )
    payload = ERROR_HEADER.pack(
        message.failed_opcode,
        int(message.error_code),
        len(encoded),
    ) + encoded
    return _make_frame(Opcode.ERROR, payload, max_payload_bytes, user_id)


def parse_error(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
) -> ErrorMessage:
    _validate_frame(frame, Opcode.ERROR, max_payload_bytes)
    reader = _PayloadReader(frame.payload)
    failed_opcode = _decode_opcode_or_raw(reader.uint16("failed_opcode"))
    raw_error_code = reader.uint16("error_code")
    message_size = reader.uint16("message_length")
    encoded = reader.read(message_size, "message")
    reader.finish()
    try:
        error_code = ErrorCode(raw_error_code)
    except ValueError as error:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"undefined error_code 0x{raw_error_code:04X}",
        ) from error
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            "ERROR message is not valid UTF-8",
        ) from error
    return ErrorMessage(failed_opcode, error_code, text)


def _validate_opcode_value(opcode: Opcode, field: str) -> None:
    if not isinstance(opcode, Opcode):
        raise ProtocolError(ErrorCode.INVALID_PAYLOAD, f"{field} is not a defined opcode")


def _decode_opcode(raw_opcode: int, field: str) -> Opcode:
    try:
        return Opcode(raw_opcode)
    except ValueError as error:
        raise ProtocolError(
            ErrorCode.INVALID_PAYLOAD,
            f"undefined {field} 0x{raw_opcode:04X}",
        ) from error


def _decode_opcode_or_raw(raw_opcode: int) -> Opcode | int:
    try:
        return Opcode(raw_opcode)
    except ValueError:
        return raw_opcode


Parser = Callable[..., object]


_PARSERS: dict[Opcode, Parser] = {
    Opcode.LOGIN: parse_login,
    Opcode.DISCONNECT: parse_disconnect,
    Opcode.FILE_LIST: parse_file_list,
    Opcode.FILE_LIST_RESP: parse_file_list_response,
    Opcode.FILE_UPLOAD: parse_file_upload,
    Opcode.FILE_DOWNLOAD: parse_file_download,
    Opcode.FILE_INFO: parse_file_info,
    Opcode.FILE_CHECKSUM: parse_file_checksum,
    Opcode.ACK: parse_acknowledgement,
    Opcode.ERROR: parse_error,
}


def decode_message(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    chunk_size_bytes: int = CHUNK_SIZE_BYTES,
) -> object:
    """Decode a supported protocol v2 frame and reject reserved opcodes."""

    if frame.opcode == Opcode.FILE_CHUNK:
        return parse_file_chunk(frame, chunk_size_bytes, max_payload_bytes)

    parser = _PARSERS.get(frame.opcode)
    if frame.opcode == Opcode.FILE_DELETE or parser is None:
        raw_opcode = int(frame.opcode)
        raise ProtocolError(
            ErrorCode.UNSUPPORTED_OPCODE,
            f"opcode 0x{raw_opcode:04X} is not supported",
        )
    return parser(frame, max_payload_bytes)


def validate_message(
    frame: Frame,
    max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    chunk_size_bytes: int = CHUNK_SIZE_BYTES,
) -> None:
    decode_message(frame, max_payload_bytes, chunk_size_bytes)
