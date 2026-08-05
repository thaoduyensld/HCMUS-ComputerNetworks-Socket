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
    make_disconnect_frame,
    parse_acknowledgement,
    parse_error,
)
from ..protocol import PREFACE_SIZE_BYTES, Frame, Opcode


class SessionError(ConnectionError):
    """Raised when the peer violates the client session handshake or lifecycle."""


SocketFactory = Callable[..., socket.socket]


class ClientSession:
    """Own one connected socket and enforce preface/disconnect handshakes."""

    def __init__(
        self,
        config: AppConfig,
        socket_factory: SocketFactory = socket.create_connection,
    ) -> None:
        self.config = config
        self._socket_factory = socket_factory
        self._socket: socket.socket | None = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def socket(self) -> socket.socket:
        if self._socket is None:
            raise SessionError("client is not connected")
        return self._socket

    def connect(self) -> None:
        if self.connected:
            raise SessionError("client is already connected")
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
            sock.settimeout(None)
        except BaseException:
            self.close(abort=True)
            raise

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
            raise SessionError("server closed the connection")
        return frame

    def disconnect(self) -> None:
        if not self.connected:
            return
        try:
            self.send(make_disconnect_frame(self.config.network.max_payload_bytes))
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
        finally:
            self.close(abort=True)

    def close(self, *, abort: bool = False) -> None:
        """Close locally; *abort* documents that no protocol exchange is attempted."""

        del abort
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()

    def __enter__(self) -> ClientSession:
        self.connect()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self.connected:
            self.disconnect()
