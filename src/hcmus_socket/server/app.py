"""Sequential TCP server application entry point."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import logging
import socket
from threading import BoundedSemaphore, Lock, Thread, current_thread

from ..config import AppConfig, load_config
from ..framing import (
    decode_preface,
    encode_preface,
    recv_exact,
    send_all,
    send_frame,
    validate_preface,
)
from ..messages import ErrorMessage, make_error_frame
from ..protocol import PREFACE_SIZE_BYTES, ErrorCode, Opcode, ProtocolError
from .logger import ServerLogger
from .registry import ActiveSessionRegistry
from .session import Handler, ServerSession


LOGGER = logging.getLogger(__name__)


class ClientWorkerGroup:
    """Own the client threads and sockets created by one server listener."""

    def __init__(
        self,
        config: AppConfig,
        handlers: Mapping[Opcode, Handler] | None,
        logger: ServerLogger,
        registry: ActiveSessionRegistry,
    ) -> None:
        self._config = config
        self._handlers = handlers
        self._logger = logger
        self._registry = registry
        self._lock = Lock()
        self._workers: dict[Thread, socket.socket] = {}
        self._slots = BoundedSemaphore(config.server.max_clients)
        self._closing = False

    def start(self, accepted_socket: socket.socket, peer_address: object) -> bool:
        """Start one admitted worker; return false when capacity is exhausted."""

        if not self._slots.acquire(blocking=False):
            return False

        worker = Thread(
            target=self._run_client,
            args=(accepted_socket, peer_address),
            name=f"hcmus-client-{peer_address}",
        )
        with self._lock:
            if self._closing:
                self._slots.release()
                accepted_socket.close()
                raise RuntimeError("client worker group is shutting down")
            self._workers[worker] = accepted_socket
        try:
            worker.start()
        except BaseException:
            with self._lock:
                self._workers.pop(worker, None)
            self._slots.release()
            accepted_socket.close()
            raise
        return True

    def close(self, *, abort_active: bool) -> None:
        """Stop accepting workers and wait until every client worker exits."""

        with self._lock:
            self._closing = True
            workers = tuple(self._workers.items())
        if abort_active:
            for _worker, client_socket in workers:
                try:
                    client_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client_socket.close()
        for worker, _client_socket in workers:
            worker.join()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._workers)

    def _run_client(
        self,
        accepted_socket: socket.socket,
        peer_address: object,
    ) -> None:
        registration = None
        try:
            registration = self._registry.register_session(peer_address)
            serve_client(
                accepted_socket,
                peer_address,
                self._config,
                self._handlers,
                self._logger,
                self._registry,
                registration.session_id,
            )
        except Exception as error:
            LOGGER.warning("client session failed: %s", error)
        finally:
            accepted_socket.close()
            if registration is not None:
                self._registry.release_session(registration.session_id)
            with self._lock:
                self._workers.pop(current_thread(), None)
            self._slots.release()


def reject_busy(
    accepted_socket: socket.socket,
    peer_address: object,
    config: AppConfig,
    logger: ServerLogger,
) -> None:
    """Complete enough of the handshake to report a connection-level error."""

    client = _client_address(peer_address)
    try:
        accepted_socket.settimeout(1.0)
        preface = recv_exact(accepted_socket, PREFACE_SIZE_BYTES)
        if preface is None:
            raise ProtocolError(
                ErrorCode.INVALID_FRAME,
                "busy client closed before sending the connection preface",
            )
        validate_preface(decode_preface(preface))
        send_all(accepted_socket, encode_preface())
        send_frame(
            accepted_socket,
            make_error_frame(
                ErrorMessage(0, ErrorCode.SERVER_BUSY, "server client limit reached"),
                config.network.max_payload_bytes,
            ),
            config.network.max_payload_bytes,
        )
        logger.log_connection(
            client,
            success=False,
            error_code=ErrorCode.SERVER_BUSY,
            message="server client limit reached",
        )
    except (OSError, ProtocolError) as error:
        LOGGER.warning("failed to reject busy client %s: %s", peer_address, error)
    finally:
        accepted_socket.close()


def _client_address(peer_address: object) -> tuple[str, int]:
    if (
        isinstance(peer_address, tuple)
        and len(peer_address) >= 2
        and isinstance(peer_address[0], str)
        and isinstance(peer_address[1], int)
    ):
        return peer_address[0], peer_address[1]
    return str(peer_address), 0


def create_listener(config: AppConfig) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((config.server.bind_address, config.server.port))
        listener.listen(socket.SOMAXCONN)
    except Exception:
        listener.close()
        raise
    return listener


def serve_client(
    accepted_socket: socket.socket,
    peer_address: object,
    config: AppConfig,
    handlers: Mapping[Opcode, Handler] | None = None,
    logger: ServerLogger | None = None,
    registry: ActiveSessionRegistry | None = None,
    registry_session_id: int | None = None,
) -> None:
    try:
        session = ServerSession(
            accepted_socket,
            peer_address,
            config,
            handlers,
            logger,
            registry,
            registry_session_id,
        )
    except Exception:
        accepted_socket.close()
        raise
    session.run()


def serve_forever(
    config: AppConfig,
    *,
    handlers: Mapping[Opcode, Handler] | None = None,
    listener: socket.socket | None = None,
    logger: ServerLogger | None = None,
    registry: ActiveSessionRegistry | None = None,
) -> None:
    config.server.storage_directory.mkdir(parents=True, exist_ok=True)
    owns_logger = logger is None
    active_logger = logger if logger is not None else ServerLogger.from_config(config)
    active_registry = registry if registry is not None else ActiveSessionRegistry()
    workers = ClientWorkerGroup(config, handlers, active_logger, active_registry)
    graceful_stop = False
    try:
        active_listener = listener if listener is not None else create_listener(config)
        try:
            while True:
                accepted_socket, peer_address = active_listener.accept()
                if not workers.start(accepted_socket, peer_address):
                    reject_busy(
                        accepted_socket,
                        peer_address,
                        config,
                        active_logger,
                    )
        except KeyboardInterrupt:
            graceful_stop = True
            return
        finally:
            active_listener.close()
            workers.close(abort_active=not graceful_stop)
    finally:
        if owns_logger:
            active_logger.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HCMUS sequential TCP server")
    parser.add_argument("config_path", help="path to the application INI file")
    arguments = parser.parse_args(argv)
    serve_forever(load_config(arguments.config_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
