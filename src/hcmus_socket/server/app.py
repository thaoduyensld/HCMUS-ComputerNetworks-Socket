"""Sequential TCP server application entry point."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import logging
import socket

from ..config import AppConfig, load_config
from ..protocol import Opcode
from .identity import IdentityRegistry
from .logger import ServerLogger
from .session import Handler, ServerSession


LOGGER = logging.getLogger(__name__)


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
    identity_registry: IdentityRegistry | None = None,
) -> None:
    try:
        session = ServerSession(
            accepted_socket,
            peer_address,
            config,
            handlers,
            logger,
            identity_registry,
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
    identity_registry: IdentityRegistry | None = None,
) -> None:
    config.server.storage_directory.mkdir(parents=True, exist_ok=True)
    owns_logger = logger is None
    active_logger = logger if logger is not None else ServerLogger.from_config(config)
    registry = identity_registry if identity_registry is not None else IdentityRegistry()
    try:
        active_listener = listener if listener is not None else create_listener(config)
        try:
            while True:
                accepted_socket, peer_address = active_listener.accept()
                try:
                    serve_client(
                        accepted_socket,
                        peer_address,
                        config,
                        handlers,
                        active_logger,
                        registry,
                    )
                except Exception as error:
                    LOGGER.warning("client session failed: %s", error)
        except KeyboardInterrupt:
            return
        finally:
            active_listener.close()
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
