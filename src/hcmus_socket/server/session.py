"""Sequential server-side protocol session lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum, auto
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
    Acknowledgement,
    ErrorMessage,
    make_acknowledgement_frame,
    make_error_frame,
    parse_disconnect,
    validate_message,
)
from ..protocol import PREFACE_SIZE_BYTES, ErrorCode, Frame, Opcode, ProtocolError
from .listing import handle_file_list


class SessionState(Enum):
    CONNECTED = auto()
    IDLE = auto()
    CLOSING = auto()
    CLOSED = auto()


class PeerDisconnected(ConnectionError):
    """Raised when a peer cleanly closes between protocol frames."""


Handler = Callable[["ServerSession", Frame], None]


class ServerSession:
    """Own one accepted socket and serve it until disconnect or failure."""

    def __init__(
        self,
        accepted_socket: socket.socket,
        peer_address: object,
        config: AppConfig,
        handlers: Mapping[Opcode, Handler] | None = None,
    ) -> None:
        self.socket = accepted_socket
        self.peer_address = peer_address
        self.config = config
        self.state = SessionState.CONNECTED
        self._handlers: dict[Opcode, Handler] = {
            Opcode.FILE_LIST: handle_file_list,
            Opcode.DISCONNECT: _handle_disconnect,
        }
        if handlers is not None:
            for opcode, handler in handlers.items():
                if opcode in self._handlers:
                    raise ValueError(f"cannot replace built-in {opcode.name} handler")
                self._handlers[opcode] = handler

    def send(self, frame: Frame) -> None:
        send_frame(
            self.socket,
            frame,
            max_payload_bytes=self.config.network.max_payload_bytes,
        )

    def receive(self) -> Frame:
        frame = receive_frame(
            self.socket,
            max_payload_bytes=self.config.network.max_payload_bytes,
        )
        if frame is None:
            raise PeerDisconnected("peer closed the connection")
        return frame

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
        self.state = SessionState.IDLE

    def serve(self) -> None:
        if self.state is not SessionState.IDLE:
            raise ProtocolError(
                ErrorCode.INVALID_STATE,
                f"dispatcher is invalid in state {self.state.name}",
            )
        while self.state is SessionState.IDLE:
            try:
                frame = self.receive()
            except PeerDisconnected:
                self.state = SessionState.CLOSING
                return
            except ProtocolError as error:
                if not error.stream_synchronized or error.raw_opcode is None:
                    raise
                self._send_error(error.raw_opcode, error)
                continue
            self._dispatch(frame)

    def run(self) -> None:
        try:
            self.perform_handshake()
            self.serve()
        finally:
            self.close()

    def close(self) -> None:
        if self.state is SessionState.CLOSED:
            return
        self.state = SessionState.CLOSING
        self.socket.close()
        self.state = SessionState.CLOSED

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
            handler(self, frame)
            if self.state not in {SessionState.CLOSING, SessionState.CLOSED}:
                self.state = SessionState.IDLE
        except ProtocolError as error:
            if self.state not in {SessionState.CLOSING, SessionState.CLOSED}:
                self.state = SessionState.IDLE
            self._send_error(frame.opcode, error)

    def _send_error(self, failed_opcode: Opcode | int, error: ProtocolError) -> None:
        self.send(
            make_error_frame(
                ErrorMessage(failed_opcode, error.code, str(error)),
                max_payload_bytes=self.config.network.max_payload_bytes,
            )
        )


def _handle_disconnect(session: ServerSession, frame: Frame) -> None:
    parse_disconnect(frame, session.config.network.max_payload_bytes)
    session.send(
        make_acknowledgement_frame(
            Acknowledgement(Opcode.DISCONNECT, 0),
            max_payload_bytes=session.config.network.max_payload_bytes,
        )
    )
    session.state = SessionState.CLOSING
