"""Sequential TCP server application entry point."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import logging
import socket
from threading import Lock, Thread, current_thread

from ..config import AppConfig, load_config
from ..protocol import Opcode
from .logger import ServerLogger
from .session import Handler, ServerSession


LOGGER = logging.getLogger(__name__)


class ClientWorkerGroup:
    """Own the client threads and sockets created by one server listener."""

    def __init__(
        self,
        config: AppConfig,
        handlers: Mapping[Opcode, Handler] | None,
        logger: ServerLogger,
    ) -> None:
        self._config = config
        self._handlers = handlers
        self._logger = logger
        self._lock = Lock()
        self._workers: dict[Thread, socket.socket] = {}
        self._closing = False

    def start(self, accepted_socket: socket.socket, peer_address: object) -> None:
        """Start one worker that owns *accepted_socket* until completion."""

        worker = Thread(
            target=self._run_client,
            args=(accepted_socket, peer_address),
            name=f"hcmus-client-{peer_address}",
        )
        with self._lock:
            if self._closing:
                accepted_socket.close()
                raise RuntimeError("client worker group is shutting down")
            self._workers[worker] = accepted_socket
        try:
            worker.start()
        except BaseException:
            with self._lock:
                self._workers.pop(worker, None)
            accepted_socket.close()
            raise

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
        try:
            serve_client(
                accepted_socket,
                peer_address,
                self._config,
                self._handlers,
                self._logger,
            )
        except Exception as error:
            LOGGER.warning("client session failed: %s", error)
        finally:
            with self._lock:
                self._workers.pop(current_thread(), None)


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
) -> None:
    try:
        session = ServerSession(
            accepted_socket,
            peer_address,
            config,
            handlers,
            logger,
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
) -> None:
    config.server.storage_directory.mkdir(parents=True, exist_ok=True)
    owns_logger = logger is None
    active_logger = logger if logger is not None else ServerLogger.from_config(config)
    workers = ClientWorkerGroup(config, handlers, active_logger)
    graceful_stop = False
    try:
        active_listener = listener if listener is not None else create_listener(config)
        try:
            while True:
                accepted_socket, peer_address = active_listener.accept()
                workers.start(accepted_socket, peer_address)
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
