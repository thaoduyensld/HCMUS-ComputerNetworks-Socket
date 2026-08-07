"""Sequential server-side protocol session lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from enum import Enum, auto
from pathlib import Path
import socket
from time import perf_counter
from typing import TypeAlias

from ..config import AppConfig
from ..framing import (
    decode_preface,
    encode_preface,
    receive_frame,
    recv_exact,
    send_all,
    send_frame,
    validate_preface,
)
from ..messages import (
    Acknowledgement,
    ErrorMessage,
    make_acknowledgement_frame,
    make_error_frame,
    parse_login,
    parse_error,
    parse_disconnect,
    parse_file_download,
    parse_file_upload,
    validate_message,
)
from ..protocol import (
    PREFACE_SIZE_BYTES,
    USER_ID,
    ErrorCode,
    Frame,
    Opcode,
    ProtocolError,
)
from ..throttling import TokenBucket
from .download import DownloadTransferResult, handle_download_frame
from .identity import (
    Identity,
    IdentityCapacityError,
    IdentityRegistry,
    UsernameInUseError as LegacyUsernameInUseError,
)
from .listing import handle_file_list
from .logger import ClientAddress, PhaseTwoLogContext, ServerLogger
from .filename_locks import FilenameLockRegistry
from .registry import (
    ActiveSessionRegistry,
    UnknownSessionError,
    UserIdCapacityError,
    UsernameInUseError,
)
from .upload import UploadTransferResult, handle_upload


class SessionState(Enum):
    CONNECTED = auto()
    AUTHENTICATING = auto()
    IDLE = auto()
    RECEIVING_UPLOAD = auto()
    SENDING_DOWNLOAD = auto()
    CLOSING = auto()
    CLOSED = auto()


class PeerDisconnected(ConnectionError):
    """Raised when a peer cleanly closes between protocol frames."""


class FatalFramingError(ConnectionError):
    """Raised when a transfer can no longer trust the incoming byte stream."""


HandlerResult: TypeAlias = DownloadTransferResult | UploadTransferResult | Frame | None
Handler = Callable[["ServerSession", Frame], HandlerResult]


class ServerSession:
    """Own one accepted socket and serve it until disconnect or failure."""

    def __init__(
        self,
        accepted_socket: socket.socket,
        peer_address: object,
        config: AppConfig,
        handlers: Mapping[Opcode, Handler] | None = None,
        logger: ServerLogger | None = None,
        registry: ActiveSessionRegistry | None = None,
        registry_session_id: int | None = None,
        filename_locks: FilenameLockRegistry | None = None,
        identity_registry: IdentityRegistry | None = None,
    ) -> None:
        self.socket = accepted_socket
        self.peer_address = peer_address
        self.config = config
        self.logger = logger
        self.registry = registry if registry is not None else ActiveSessionRegistry()
        self._owns_registry_session = registry_session_id is None
        if registry_session_id is None:
            registry_session_id = self.registry.register_session(peer_address).session_id
        self.registry_session_id = registry_session_id
        self.filename_locks = filename_locks
        self.identity_registry = identity_registry
        self.identity: Identity | None = None
        limit_kib = config.network.bandwidth_limit_kib_per_second
        self.bandwidth_limiter = (
            None
            if limit_kib == 0
            else TokenBucket(
                rate_bytes_per_second=limit_kib * 1024,
                burst_bytes=config.network.chunk_size_bytes,
            )
        )
        self.state = SessionState.CONNECTED
        self.username: str | None = None
        self.user_id = USER_ID
        self.authenticated = False
        self._clean_disconnect = False
        self._handlers: dict[Opcode, Handler] = {
            Opcode.FILE_LIST: handle_file_list,
            Opcode.FILE_UPLOAD: handle_upload,
            Opcode.FILE_DOWNLOAD: handle_download_frame,
            Opcode.DISCONNECT: _handle_disconnect,
        }
        if handlers is not None:
            for opcode, handler in handlers.items():
                if opcode in {Opcode.FILE_LIST, Opcode.DISCONNECT}:
                    raise ValueError(f"cannot replace built-in {opcode.name} handler")
                self._handlers[opcode] = handler

    def send(self, frame: Frame) -> None:
        if frame.user_id != self.user_id:
            raise ProtocolError(
                ErrorCode.INVALID_USER_ID,
                f"outgoing {frame.opcode.name} USER_ID does not match the session",
            )
        send_frame(
            self.socket,
            frame,
            max_payload_bytes=self.config.network.max_payload_bytes,
        )

    def receive(self) -> Frame:
        try:
            frame = receive_frame(
                self.socket,
                max_payload_bytes=self.config.network.max_payload_bytes,
            )
        except ProtocolError as error:
            if self.state in {
                SessionState.RECEIVING_UPLOAD,
                SessionState.SENDING_DOWNLOAD,
            } and (
                error.code in {ErrorCode.INVALID_FRAME, ErrorCode.PAYLOAD_TOO_LARGE}
                and not error.stream_synchronized
            ):
                raise FatalFramingError(str(error)) from error
            raise
        if frame is None:
            raise PeerDisconnected("peer closed the connection")
        expected_user_id = (
            USER_ID if self.state is SessionState.AUTHENTICATING else self.user_id
        )
        if frame.user_id != expected_user_id:
            raise ProtocolError(
                ErrorCode.INVALID_USER_ID,
                f"incoming {frame.opcode.name} USER_ID does not match the session",
                raw_opcode=int(frame.opcode),
                stream_synchronized=True,
            )
        return frame

    def consume_bandwidth(self, amount: int) -> float:
        """Throttle file-data bytes for this session; control frames are free."""

        if self.bandwidth_limiter is None:
            return 0.0
        return self.bandwidth_limiter.consume(amount)

    def perform_handshake(self) -> None:
        if self.state is not SessionState.CONNECTED:
            raise ProtocolError(
                ErrorCode.INVALID_STATE,
                f"handshake is invalid in state {self.state.name}",
            )
        encoded = recv_exact(self.socket, PREFACE_SIZE_BYTES)
        if encoded is None:
            raise ProtocolError(
                ErrorCode.INVALID_FRAME,
                "peer closed before sending the connection preface",
            )
        validate_preface(decode_preface(encoded))
        send_all(self.socket, encode_preface())
        self.state = SessionState.AUTHENTICATING

    def serve(self) -> None:
        if self.state not in {SessionState.AUTHENTICATING, SessionState.IDLE}:
            raise ProtocolError(
                ErrorCode.INVALID_STATE,
                f"dispatcher is invalid in state {self.state.name}",
            )
        while self.state in {SessionState.AUTHENTICATING, SessionState.IDLE}:
            try:
                frame = self.receive()
            except PeerDisconnected:
                self.state = SessionState.CLOSING
                return
            except ProtocolError as error:
                if not error.stream_synchronized or error.raw_opcode is None:
                    raise
                self._send_error(error.raw_opcode, error)
                if error.code is ErrorCode.INVALID_USER_ID:
                    self.state = SessionState.CLOSING
                    return
                continue
            if self.state is SessionState.AUTHENTICATING:
                self._dispatch_authentication(frame)
            else:
                self._dispatch(frame)

    def run(self) -> None:
        handshake_completed = False
        failure: BaseException | None = None
        try:
            try:
                self.perform_handshake()
                handshake_completed = True
                if self.logger is not None:
                    self.logger.log_connection(
                        self.client_address,
                        context=self.log_context,
                    )
            except BaseException as error:
                if self.logger is not None:
                    self.logger.log_connection(
                        self.client_address,
                        success=False,
                        error_code=_error_code(error),
                        message=str(error),
                        context=self.log_context,
                    )
                raise
            self.serve()
        except BaseException as error:
            failure = error
            raise
        finally:
            self.close()
            if self.logger is not None:
                self.logger.log_disconnection(
                    self.client_address,
                    clean=handshake_completed and self._clean_disconnect,
                    message=str(failure) if failure is not None else None,
                    context=self.log_context,
                )

    @property
    def client_address(self) -> ClientAddress:
        if (
            isinstance(self.peer_address, tuple)
            and len(self.peer_address) >= 2
            and isinstance(self.peer_address[0], str)
            and isinstance(self.peer_address[1], int)
        ):
            return self.peer_address[0], self.peer_address[1]
        return str(self.peer_address), 0

    @property
    def log_context(self) -> PhaseTwoLogContext:
        username = None
        user_id = None
        if self.registry is not None and self.registry_session_id is not None:
            try:
                record = self.registry.get_session(self.registry_session_id)
            except UnknownSessionError:
                pass
            else:
                username = record.username
                user_id = record.user_id
        return PhaseTwoLogContext(
            session_id=self.registry_session_id,
            username=username,
            user_id=user_id,
            bandwidth_limit_bps=getattr(
                self.config.network,
                "bandwidth_limit_bytes_per_second",
                None,
            ),
        )

    def close(self) -> None:
        if self.state is SessionState.CLOSED:
            return
        self.state = SessionState.CLOSING
        if self._owns_registry_session:
            self.registry.release_session(self.registry_session_id)
        if self.identity_registry is not None and self.identity is not None:
            self.identity_registry.release(self.identity)
            self.identity = None
        self.authenticated = False
        self.username = None
        self.user_id = USER_ID
        try:
            self.socket.close()
        finally:
            self.state = SessionState.CLOSED

    @property
    def storage_directory(self) -> Path:
        if self.username is None:
            raise ProtocolError(
                ErrorCode.AUTHENTICATION_REQUIRED,
                "authenticated username is required for storage access",
            )
        return self.config.server.storage_directory / self.username

    def __enter__(self) -> "ServerSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _dispatch(self, frame: Frame) -> None:
        if self.state is not SessionState.IDLE:
            self._send_error(
                frame.opcode,
                ProtocolError(ErrorCode.INVALID_STATE, "session is not idle"),
            )
            return
        started = perf_counter()
        try:
            validate_message(
                frame,
                max_payload_bytes=self.config.network.max_payload_bytes,
                chunk_size_bytes=self.config.network.chunk_size_bytes,
            )
            handler = self._handlers.get(frame.opcode)
            if handler is None:
                raise ProtocolError(
                    ErrorCode.UNSUPPORTED_OPCODE,
                    f"{frame.opcode.name} is not integrated on the server",
                )
            self.begin_request(frame.opcode)
            with self._filename_guard(frame):
                result = handler(self, frame)
            if self.state not in {SessionState.CLOSING, SessionState.CLOSED}:
                self.finish_request()
            self._log_command(frame, result, started)
        except ProtocolError as error:
            if self.state not in {SessionState.CLOSING, SessionState.CLOSED}:
                self.state = SessionState.IDLE
            self._send_error(frame.opcode, error)
            self._log_command(frame, None, started, error=error)
        except (ConnectionError, TimeoutError, OSError) as error:
            self._log_command(frame, None, started, error=error)
            raise

    def _filename_guard(self, frame: Frame) -> AbstractContextManager[None]:
        if self.filename_locks is None:
            return nullcontext()
        if frame.opcode is Opcode.FILE_UPLOAD:
            filename = parse_file_upload(
                frame,
                self.config.network.max_payload_bytes,
            ).filename
        elif frame.opcode is Opcode.FILE_DOWNLOAD:
            filename = parse_file_download(
                frame,
                self.config.network.max_payload_bytes,
            ).filename
        else:
            return nullcontext()
        return self.filename_locks.hold(self.filename_namespace, filename)

    @property
    def filename_namespace(self) -> str:
        if self.registry is None or self.registry_session_id is None:
            return ""
        record = self.registry.get_session(self.registry_session_id)
        return record.username or ""

    def _dispatch_authentication(self, frame: Frame) -> None:
        if frame.opcode is not Opcode.LOGIN:
            self._send_error(
                frame.opcode,
                ProtocolError(
                    ErrorCode.AUTHENTICATION_REQUIRED,
                    "LOGIN is required before file commands",
                ),
            )
            return
        try:
            request = parse_login(
                frame,
                max_payload_bytes=self.config.network.max_payload_bytes,
            )
            if len(request.username.encode("utf-8")) > self.config.auth.max_username_bytes:
                raise ProtocolError(
                    ErrorCode.INVALID_USERNAME,
                    "username exceeds the configured byte limit",
                )
            self._authenticate(request.username)
        except ProtocolError as error:
            self._send_error(Opcode.LOGIN, error)

    def _authenticate(self, username: str) -> None:
        if self.identity_registry is not None:
            self._authenticate_legacy(username)
            return
        try:
            identity = self.registry.claim_username(self.registry_session_id, username)
        except UsernameInUseError as error:
            raise ProtocolError(ErrorCode.USERNAME_IN_USE, str(error)) from error
        except UserIdCapacityError as error:
            raise ProtocolError(ErrorCode.SERVER_BUSY, str(error)) from error

        try:
            namespace = self.config.server.storage_directory / username
            namespace.mkdir(parents=True, exist_ok=True)
        except PermissionError as error:
            raise ProtocolError(
                ErrorCode.ACCESS_DENIED,
                f"cannot create user namespace: {error}",
            ) from error
        except OSError as error:
            raise ProtocolError(
                ErrorCode.FILE_IO_ERROR,
                f"cannot create user namespace: {error}",
            ) from error

        self.username = identity.username
        self.user_id = identity.user_id
        self.send(
            make_acknowledgement_frame(
                Acknowledgement(Opcode.LOGIN, 0),
                max_payload_bytes=self.config.network.max_payload_bytes,
                user_id=self.user_id,
            )
        )
        self.authenticated = True
        self.state = SessionState.IDLE

    def _authenticate_legacy(self, username: str) -> None:
        try:
            identity = self.identity_registry.register(username)
        except LegacyUsernameInUseError as error:
            raise ProtocolError(ErrorCode.USERNAME_IN_USE, str(error)) from error
        except IdentityCapacityError as error:
            raise ProtocolError(ErrorCode.SERVER_BUSY, str(error)) from error
        namespace = self.config.server.storage_directory / username
        try:
            namespace.mkdir(parents=True, exist_ok=True)
        except PermissionError as error:
            self.identity_registry.release(identity)
            raise ProtocolError(ErrorCode.ACCESS_DENIED, str(error)) from error
        except OSError as error:
            self.identity_registry.release(identity)
            raise ProtocolError(ErrorCode.FILE_IO_ERROR, str(error)) from error
        self.identity = identity
        self.username = identity.username
        self.user_id = identity.user_id
        self.send(make_acknowledgement_frame(
            Acknowledgement(Opcode.LOGIN, 0),
            max_payload_bytes=self.config.network.max_payload_bytes,
            user_id=self.user_id,
        ))
        self.authenticated = True
        self.state = SessionState.IDLE

    def _log_command(
        self,
        frame: Frame,
        result: HandlerResult,
        started: float,
        *,
        error: BaseException | None = None,
    ) -> None:
        if self.logger is None:
            return
        if isinstance(result, DownloadTransferResult):
            self.logger.log_download(
                self.client_address,
                result,
                context=self.log_context,
                resume_offset=_resume_offset(frame, self.config.network.max_payload_bytes),
            )
            return
        if isinstance(result, UploadTransferResult):
            self.logger.log_upload(
                self.client_address,
                result,
                context=self.log_context,
                resume_offset=_resume_offset(frame, self.config.network.max_payload_bytes),
            )
            return
        response_error = (
            parse_error(result, self.config.network.max_payload_bytes)
            if isinstance(result, Frame) and result.opcode is Opcode.ERROR
            else None
        )
        logged_error = response_error.error_code if response_error is not None else _error_code(error)
        message = response_error.message if response_error is not None else (
            str(error) if error is not None else None
        )
        self.logger.log_transfer(
            self.client_address,
            frame.opcode,
            filename=None,
            bytes_transferred=len(result.payload) if isinstance(result, Frame) else 0,
            duration_seconds=perf_counter() - started,
            success=error is None and response_error is None,
            error_code=logged_error,
            message=message,
            context=self.log_context,
            resume_offset=_resume_offset(frame, self.config.network.max_payload_bytes),
        )

    def begin_request(self, opcode: Opcode) -> None:
        """Enter the state required by a validated top-level request."""

        if self.state is not SessionState.IDLE:
            raise ProtocolError(
                ErrorCode.INVALID_STATE,
                f"cannot start {opcode.name} in state {self.state.name}",
            )
        if opcode is Opcode.FILE_UPLOAD:
            self.state = SessionState.RECEIVING_UPLOAD
        elif opcode is Opcode.FILE_DOWNLOAD:
            self.state = SessionState.SENDING_DOWNLOAD

    def finish_request(self) -> None:
        """Return a completed or recoverably failed request to IDLE."""

        if self.state not in {
            SessionState.IDLE,
            SessionState.RECEIVING_UPLOAD,
            SessionState.SENDING_DOWNLOAD,
        }:
            raise ProtocolError(
                ErrorCode.INVALID_STATE,
                f"cannot finish a request in state {self.state.name}",
            )
        self.state = SessionState.IDLE

    def _send_error(self, failed_opcode: Opcode | int, error: ProtocolError) -> None:
        self.send(
            make_error_frame(
                ErrorMessage(failed_opcode, error.code, str(error)),
                max_payload_bytes=self.config.network.max_payload_bytes,
                user_id=self.user_id,
            )
        )


def _handle_disconnect(session: ServerSession, frame: Frame) -> None:
    parse_disconnect(frame, session.config.network.max_payload_bytes)
    session.send(
        make_acknowledgement_frame(
            Acknowledgement(Opcode.DISCONNECT, 0),
            max_payload_bytes=session.config.network.max_payload_bytes,
            user_id=session.user_id,
        )
    )
    session._clean_disconnect = True
    session.state = SessionState.CLOSING


def _error_code(error: BaseException | None) -> ErrorCode | None:
    if isinstance(error, ProtocolError):
        return error.code
    if error is not None:
        return ErrorCode.INTERNAL_ERROR
    return None


def _resume_offset(frame: Frame, max_payload_bytes: int) -> int | None:
    try:
        if frame.opcode is Opcode.FILE_UPLOAD:
            return parse_file_upload(frame, max_payload_bytes).start_offset
        if frame.opcode is Opcode.FILE_DOWNLOAD:
            return parse_file_download(frame, max_payload_bytes).requested_offset
    except ProtocolError:
        return None
    return None
