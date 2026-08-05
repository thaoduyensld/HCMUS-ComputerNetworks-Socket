"""Command-line entry point and command dispatch for the client."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import sys
from typing import TextIO

from ..config import ConfigError, load_config
from ..protocol import ProtocolError
from .commands import Command, CommandName, CommandSyntaxError, parse_command
from .session import ClientSession


CommandHandler = Callable[[ClientSession, Command], None]


def run_cli(
    session: ClientSession,
    handlers: Mapping[CommandName, CommandHandler],
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> None:
    """Read commands until QUIT/EOF and dispatch file operations to handlers."""

    print("Commands: LIST, UPLOAD <filename>, DOWNLOAD <filename>", file=output_stream)
    while True:
        print("> ", end="", file=output_stream, flush=True)
        line = input_stream.readline()
        if line == "":
            break
        try:
            command = parse_command(line)
        except CommandSyntaxError as error:
            print(f"Command error: {error}", file=error_stream)
            continue
        if command.name is CommandName.QUIT:
            break
        handler = handlers.get(command.name)
        if handler is None:
            print(
                f"{command.name.value} handler is not integrated yet",
                file=error_stream,
            )
            continue
        try:
            handler(session, command)
        except (OSError, ConnectionError, ProtocolError) as error:
            print(f"{command.name.value} failed: {error}", file=error_stream)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hcmus-socket-client")
    parser.add_argument("config", help="path to the application INI file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        config = load_config(arguments.config)
        session = ClientSession(config)
        session.connect()
        try:
            print(
                f"Connected to {config.client.server_address}:"
                f"{config.client.server_port}"
            )
            run_cli(session, {})
            session.disconnect()
        finally:
            session.close(abort=True)
        return 0
    except (ConfigError, OSError, ConnectionError, ProtocolError) as error:
        print(f"Client error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
