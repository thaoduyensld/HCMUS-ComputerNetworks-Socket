"""Command-line entry point and command dispatch for the client."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import sys
from typing import TextIO

from ..config import ConfigError, load_config
from ..protocol import ProtocolError
from .commands import Command, CommandName, CommandSyntaxError, parse_command
from .download import download_file
from .listing import list_files
from .session import ClientSession
from .upload import upload_file


CommandHandler = Callable[[ClientSession, Command], None]


def handle_list(session: ClientSession, command: Command) -> None:
    """CLI adapter for one FILE_LIST request."""

    if command.filename is not None:
        raise CommandSyntaxError("LIST does not accept arguments")
    response = list_files(session)
    if not response.entries:
        print("No files available.")
        return
    for entry in response.entries:
        print(f"{entry.filename:<30} {entry.file_size:>12} bytes")


def handle_download(session: ClientSession, command: Command) -> None:
    """CLI adapter for the streaming download workflow."""

    if command.filename is None:
        raise CommandSyntaxError("usage: DOWNLOAD <filename>")
    last_percent = -1

    def show_progress(received: int, total: int, percent: int) -> None:
        nonlocal last_percent
        if percent != last_percent:
            print(
                f"\rDownloading {command.filename}: {percent}% "
                f"({received}/{total} bytes)",
                end="",
                flush=True,
            )
            last_percent = percent

    result = download_file(session, command.filename, progress=show_progress)
    print(
        f"\nDownloaded {result.path} ({result.bytes_received} bytes, SHA-256 matched)"
    )


def handle_upload(session: ClientSession, command: Command) -> None:
    """CLI adapter for the streaming upload workflow."""

    if command.filename is None:
        raise CommandSyntaxError("usage: UPLOAD <filename>")
    source = command.filename
    remote_filename = Path(source).name
    last_percent = -1

    def show_progress(sent: int, total: int, percent: int) -> None:
        nonlocal last_percent
        if percent != last_percent:
            print(
                f"\rUploading {remote_filename}: {percent}% "
                f"({sent}/{total} bytes)",
                end="",
                flush=True,
            )
            last_percent = percent

    result = upload_file(
        session,
        source,
        remote_filename,
        progress=show_progress,
    )
    print(
        f"\nUploaded {result.remote_filename} "
        f"({result.bytes_sent} bytes, SHA-256 matched)"
    )


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
        except (ConnectionError, TimeoutError) as error:
            print(f"{command.name.value} failed: {error}", file=error_stream)
            return
        except (OSError, ProtocolError) as error:
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
            run_cli(
                session,
                {
                    CommandName.LIST: handle_list,
                    CommandName.UPLOAD: handle_upload,
                    CommandName.DOWNLOAD: handle_download,
                },
            )
            session.disconnect()
        finally:
            session.close(abort=True)
        return 0
    except (ConfigError, OSError, ConnectionError, ProtocolError) as error:
        print(f"Client error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
