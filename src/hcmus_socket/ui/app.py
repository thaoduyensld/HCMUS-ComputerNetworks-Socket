"""Desktop application shell for the HCMUS socket client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import tkinter as tk
from tkinter import messagebox, ttk

from ..client.api import ClientApi
from ..client.session import AuthenticationError, SessionError
from ..config import AppConfig
from ..messages import FileListResponse
from ..protocol import ProtocolError
from .connection_view import ConnectionView
from .file_view import FileView
from .transfer_view import TransferView
from .worker import BackgroundWorker, UiEvent, UiEventKind


ApiFactory = Callable[..., ClientApi]
CONNECT_TASK = "connect"
DISCONNECT_TASK = "disconnect"
REFRESH_TASK = "refresh"


class DesktopApp:
    """Compose the desktop views and own their background worker."""

    POLL_INTERVAL_MS = 50

    def __init__(
        self,
        root: tk.Tk,
        *,
        config: AppConfig | None = None,
        api_factory: ApiFactory = ClientApi,
    ) -> None:
        self.root = root
        self.base_config = config if config is not None else AppConfig()
        self.api_factory = api_factory
        self.api: ClientApi | None = None
        self._file_task_pending = False
        self.worker = BackgroundWorker()
        self.status = tk.StringVar(value="Disconnected")

        root.title("HCMUS Socket File Client")
        root.geometry("760x560")
        root.minsize(640, 460)

        container = ttk.Frame(root, padding=12)
        container.pack(fill="both", expand=True)
        self.connection_view = ConnectionView(
            container,
            on_connect=self.connect,
            on_disconnect=self.disconnect,
        )
        self.file_view = FileView(
            container,
            on_refresh=self.refresh_files,
            on_upload=self._not_integrated,
            on_download=self._not_integrated,
        )
        self.transfer_view = TransferView(container)
        self.connection_view.pack(fill="x")
        self.file_view.pack(fill="both", expand=True, pady=12)
        self.transfer_view.pack(fill="x")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(
            side="bottom", fill="x"
        )

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<F5>", self._refresh_shortcut)
        root.after(self.POLL_INTERVAL_MS, self._poll_worker)

    def close(self) -> None:
        if self.api is not None:
            self.api.close(abort=True)
            self.api = None
        self.worker.close()
        self.root.destroy()

    def connect(self) -> None:
        if self.api is not None or self.worker.closed:
            return
        try:
            host, port, username = self.connection_view.credentials()
        except ValueError as error:
            messagebox.showerror("Invalid connection", str(error), parent=self.root)
            return

        config = connection_config(self.base_config, host, port)
        api = self.api_factory(config, username=username)
        self.api = api
        self.connection_view.set_state(connected=False, busy=True)
        self.file_view.set_enabled(False)
        self.status.set(f"Connecting to {host}:{port}…")
        self.worker.submit(CONNECT_TASK, api.connect)

    def disconnect(self) -> None:
        if self.api is None or not self.api.connected:
            return
        self.connection_view.set_state(connected=True, busy=True)
        self.file_view.set_enabled(False)
        self.status.set("Disconnecting…")
        self.worker.submit(DISCONNECT_TASK, self.api.disconnect)

    def refresh_files(self) -> None:
        if (
            self.api is None
            or not self.api.authenticated
            or self._file_task_pending
        ):
            return
        self._file_task_pending = True
        self.file_view.set_enabled(False)
        self.status.set("Refreshing remote files…")
        self.worker.submit(REFRESH_TASK, self.api.list_files)

    def _poll_worker(self) -> None:
        event = self.worker.poll()
        while event is not None:
            self.handle_event(event)
            event = self.worker.poll()
        if not self.worker.closed:
            self.root.after(self.POLL_INTERVAL_MS, self._poll_worker)

    def handle_event(self, event: UiEvent[object]) -> None:
        if event.kind is UiEventKind.TASK_STARTED:
            return
        if event.kind is UiEventKind.TASK_FAILED:
            self._handle_failure(event.task_name, event.error)
            return
        if event.kind is UiEventKind.TASK_COMPLETED:
            if event.task_name == CONNECT_TASK:
                self._handle_connected()
            elif event.task_name == DISCONNECT_TASK:
                self._handle_disconnected()
            elif event.task_name == REFRESH_TASK:
                self._handle_refreshed(event.payload)

    def _handle_connected(self) -> None:
        if self.api is None:
            return
        self.connection_view.set_state(connected=True)
        self.file_view.set_enabled(True)
        self.status.set(
            f"Connected as {self.api.username} (user ID {self.api.user_id})"
        )
        self.refresh_files()

    def _handle_refreshed(self, payload: object | None) -> None:
        self._file_task_pending = False
        if not isinstance(payload, FileListResponse):
            self._handle_file_failure(
                REFRESH_TASK,
                RuntimeError("worker returned an invalid file-list result"),
            )
            return
        self.file_view.replace_files(payload.entries)
        self.file_view.set_enabled(True)
        count = len(payload.entries)
        suffix = "file" if count == 1 else "files"
        self.status.set(f"Connected — {count} remote {suffix}")

    def _handle_disconnected(self) -> None:
        self.api = None
        self._file_task_pending = False
        self.connection_view.set_state(connected=False)
        self.file_view.set_enabled(False)
        self.file_view.replace_files(())
        self.transfer_view.reset()
        self.status.set("Disconnected")

    def _handle_failure(self, task_name: str, error: Exception | None) -> None:
        if task_name == REFRESH_TASK:
            self._handle_file_failure(task_name, error)
            return
        message = connection_error_message(error)
        if self.api is not None:
            self.api.close(abort=True)
        self.api = None
        self.connection_view.set_state(connected=False)
        self.file_view.set_enabled(False)
        self.status.set(f"{task_name.capitalize()} failed: {message}")
        messagebox.showerror(
            f"{task_name.capitalize()} failed",
            message,
            parent=self.root,
        )

    def _handle_file_failure(
        self,
        task_name: str,
        error: Exception | None,
    ) -> None:
        self._file_task_pending = False
        message = connection_error_message(error)
        still_connected = self.api is not None and self.api.connected
        self.file_view.set_enabled(still_connected)
        if still_connected:
            self.connection_view.set_state(connected=True)
            self.status.set(f"{task_name.capitalize()} failed: {message}")
        else:
            if self.api is not None:
                self.api.close(abort=True)
            self.api = None
            self.connection_view.set_state(connected=False)
            self.file_view.replace_files(())
            self.status.set("Disconnected")
        messagebox.showerror(
            f"{task_name.capitalize()} failed",
            message,
            parent=self.root,
        )

    def _refresh_shortcut(self, _event: tk.Event[tk.Misc]) -> str:
        self.refresh_files()
        return "break"

    def _not_integrated(self) -> None:
        messagebox.showinfo(
            "Desktop UI",
            "Networking actions will be connected in the next implementation step.",
            parent=self.root,
        )


def connection_config(base: AppConfig, host: str, port: int) -> AppConfig:
    """Return a connection-specific config without mutating shared defaults."""

    return replace(
        base,
        client=replace(base.client, server_address=host, server_port=port),
    )


def connection_error_message(error: Exception | None) -> str:
    if error is None:
        return "unknown connection error"
    if isinstance(error, AuthenticationError):
        return str(error)
    if isinstance(error, (SessionError, ProtocolError, OSError, TimeoutError)):
        return str(error)
    return f"unexpected error: {error}"


def main() -> int:
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
