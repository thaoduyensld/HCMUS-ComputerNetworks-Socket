"""TCP connection lifecycle for the interactive client."""

from __future__ import annotations

from collections.abc import Callable
import socket

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
    LoginRequest,
    make_disconnect_frame,
    make_login_frame,
    parse_acknowledgement,
    parse_error,
)
from ..protocol import (
    MAX_USER_ID,
    MIN_USER_ID,
    PREFACE_SIZE_BYTES,
    USER_ID,
    ErrorCode,
    Frame,
    Opcode,
    ProtocolError,
)


class SessionError(ConnectionError):
    """Raised when the peer violates the client session handshake or lifecycle."""


class AuthenticationError(SessionError):
    """Raised when the server rejects LOGIN or returns an invalid LOGIN response."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


SocketFactory = Callable[..., socket.socket]


class ClientSession:
    """Own one connected socket and enforce preface/disconnect handshakes."""

    def __init__(
        self,
        config: AppConfig,
        socket_factory: SocketFactory = socket.create_connection,
        *,
        username: str | None = None,
    ) -> None:
        self.config = config
        self._socket_factory = socket_factory
        self._socket: socket.socket | None = None
        self.username = username
        self.user_id = USER_ID
        self.authenticated = False

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def socket(self) -> socket.socket:
        if self._socket is None:
            raise SessionError("client is not connected")
        return self._socket

    def connect(self, username: str | None = None) -> None:
        if self.connected:
            raise SessionError("client is already connected")
        selected_username = username if username is not None else self.username
        if selected_username is None:
            raise SessionError("username is required to connect")
        login_frame = make_login_frame(
            LoginRequest(selected_username),
            max_payload_bytes=self.config.network.max_payload_bytes,
        )
        if len(selected_username.encode("utf-8")) > self.config.auth.max_username_bytes:
            raise AuthenticationError(
                ErrorCode.INVALID_USERNAME,
                "username exceeds the configured byte limit",
            )
        self.username = selected_username
        address = (
            self.config.client.server_address,
            self.config.client.server_port,
        )
        timeout = self.config.client.connect_timeout_ms / 1000
        sock = self._socket_factory(address, timeout=timeout)
        self._socket = sock
        try:
            send_all(sock, encode_preface())
            response = recv_exact(sock, PREFACE_SIZE_BYTES)
            if response is None:
                raise SessionError("server closed before returning protocol preface")
            validate_preface(decode_preface(response))
            self.send(login_frame)
            self._complete_login(self.receive())
            sock.settimeout(None)
        except BaseException:
            self.close(abort=True)
            raise

    def send(self, frame: Frame) -> None:
        try:
            self._validate_outgoing_user_id(frame)
            send_frame(
                self.socket,
                frame,
                max_payload_bytes=self.config.network.max_payload_bytes,
            )
        except OSError as error:
            self.close(abort=True)
            raise SessionError(f"failed to send frame: {error}") from error

    def receive(self) -> Frame:
        try:
            frame = receive_frame(
                self.socket,
                max_payload_bytes=self.config.network.max_payload_bytes,
            )
        except (OSError, ProtocolError) as error:
            self.close(abort=True)
            raise SessionError(f"failed to receive a complete frame: {error}") from error
        if frame is None:
            self.close(abort=True)
            raise SessionError("server closed the connection")
        try:
            self._validate_incoming_user_id(frame)
        except ProtocolError as error:
            self.close(abort=True)
            raise SessionError(f"server sent an invalid session frame: {error}") from error
        return frame

    def disconnect(self) -> None:
        if not self.connected:
            return
        try:
            self.send(
                make_disconnect_frame(
                    self.config.network.max_payload_bytes,
                    user_id=self.user_id,
                )
            )
            response = self.receive()
            if response.opcode is Opcode.ERROR:
                error = parse_error(response, self.config.network.max_payload_bytes)
                raise SessionError(f"server rejected DISCONNECT: {error.message}")
            acknowledgement = parse_acknowledgement(
                response,
                self.config.network.max_payload_bytes,
            )
            if acknowledgement.acknowledged_opcode is not Opcode.DISCONNECT:
                raise SessionError("server acknowledged the wrong opcode")
            if acknowledgement.next_offset != 0:
                raise SessionError("DISCONNECT ACK next_offset must be zero")
        finally:
            self.close(abort=True)

    def close(self, *, abort: bool = False) -> None:
        """Close locally; *abort* documents that no protocol exchange is attempted."""

        sock, self._socket = self._socket, None
        self.authenticated = False
        self.user_id = USER_ID
        if sock is not None:
            if abort:
                try:
                    shutdown = getattr(sock, "shutdown", None)
                    if shutdown is not None:
                        shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            sock.close()

    def _validate_outgoing_user_id(self, frame: Frame) -> None:
        if not self.authenticated and frame.opcode is not Opcode.LOGIN:
            raise ProtocolError(
                ErrorCode.AUTHENTICATION_REQUIRED,
                "LOGIN is required before sending file commands",
            )
        expected = USER_ID if frame.opcode is Opcode.LOGIN else self.user_id
        if frame.user_id != expected:
            raise ProtocolError(
                ErrorCode.INVALID_USER_ID,
                f"outgoing {frame.opcode.name} USER_ID must be {expected}",
            )

    def _validate_incoming_user_id(self, frame: Frame) -> None:
        if not self.authenticated and frame.opcode is Opcode.ACK:
            acknowledgement = parse_acknowledgement(
                frame,
                self.config.network.max_payload_bytes,
            )
            if acknowledgement.acknowledged_opcode is Opcode.LOGIN:
                if not 1 <= frame.user_id <= MAX_USER_ID:
                    raise ProtocolError(
                        ErrorCode.INVALID_USER_ID,
                        "LOGIN ACK must assign a nonzero USER_ID",
                    )
                self.user_id = frame.user_id
                return
        if not self.authenticated and frame.opcode is Opcode.ERROR:
            if frame.user_id != USER_ID:
                raise ProtocolError(
                    ErrorCode.INVALID_USER_ID,
                    "pre-login ERROR frame USER_ID must be zero",
                )
            return
        if frame.user_id != self.user_id:
            raise ProtocolError(
                ErrorCode.INVALID_USER_ID,
                f"incoming {frame.opcode.name} USER_ID does not match the session",
            )

    def _complete_login(self, frame: Frame) -> None:
        if frame.opcode is Opcode.ERROR:
            error = parse_error(frame, self.config.network.max_payload_bytes)
            raise AuthenticationError(
                error.error_code,
                f"LOGIN failed ({error.error_code.name}): {error.message}",
            )
        if frame.opcode is not Opcode.ACK:
            raise AuthenticationError(
                ErrorCode.INVALID_STATE,
                f"expected ACK(LOGIN), got {frame.opcode.name}",
            )
        acknowledgement = parse_acknowledgement(
            frame,
            self.config.network.max_payload_bytes,
        )
        if acknowledgement.acknowledged_opcode is not Opcode.LOGIN:
            raise AuthenticationError(
                ErrorCode.INVALID_STATE,
                "server acknowledged the wrong opcode during LOGIN",
            )
        if acknowledgement.next_offset != 0:
            raise AuthenticationError(
                ErrorCode.INVALID_PAYLOAD,
                "LOGIN ACK next_offset must be zero",
            )
        if not MIN_USER_ID <= self.user_id <= MAX_USER_ID:
            raise AuthenticationError(
                ErrorCode.INVALID_USER_ID,
                "LOGIN ACK did not assign a valid user ID",
            )
        self.authenticated = True

    def __enter__(self) -> ClientSession:
        self.connect()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self.connected:
            self.disconnect()
