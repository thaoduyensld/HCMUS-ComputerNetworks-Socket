from __future__ import annotations

from io import StringIO

from hcmus_socket.client.app import run_cli
from hcmus_socket.client.commands import Command, CommandName


def test_cli_dispatches_handlers_and_stops_on_quit() -> None:
    input_stream = StringIO("bad\nLIST\nDOWNLOAD data.bin\nQUIT\nLIST\n")
    output = StringIO()
    errors = StringIO()
    handled: list[Command] = []

    handlers = {
        CommandName.LIST: lambda _session, command: handled.append(command),
        CommandName.DOWNLOAD: lambda _session, command: handled.append(command),
    }
    run_cli(
        object(),  # type: ignore[arg-type]
        handlers,
        input_stream=input_stream,
        output_stream=output,
        error_stream=errors,
    )

    assert handled == [
        Command(CommandName.LIST),
        Command(CommandName.DOWNLOAD, "data.bin"),
    ]
    assert "Command error" in errors.getvalue()


def test_cli_reports_handler_that_is_not_integrated() -> None:
    errors = StringIO()

    run_cli(
        object(),  # type: ignore[arg-type]
        {},
        input_stream=StringIO("UPLOAD data.bin\n"),
        output_stream=StringIO(),
        error_stream=errors,
    )

    assert "UPLOAD handler is not integrated yet" in errors.getvalue()
