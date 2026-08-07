"""Desktop application shell for the HCMUS socket client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..client.api import ClientApi
from ..client.download import DownloadResult
from ..client.session import AuthenticationError, SessionError
from ..client.upload import UploadResult
from ..config import AppConfig
from ..messages import FileListResponse
from ..protocol import ErrorCode, ProtocolError
from .connection_view import ConnectionView
from .file_view import FileView
from .transfer_view import TransferView
from .worker import BackgroundWorker, UiEvent, UiEventKind


ApiFactory = Callable[..., ClientApi]
CONNECT_TASK = "connect"
DISCONNECT_TASK = "disconnect"
REFRESH_TASK = "refresh"
UPLOAD_TASK = "upload"
DOWNLOAD_TASK = "download"


@dataclass(frozen=True, slots=True)
class TransferProgress:
    action: str
    filename: str
    done: int
    total: int
    percent: int


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
        self._active_transfer: tuple[str, str] | None = None
        self._cancel_requested: str | None = None
        self._closing = False
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
            on_upload=self.upload_file,
            on_download=self.download_file,
        )
        self.transfer_view = TransferView(container, on_cancel=self.cancel_transfer)
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
        if self._closing:
            return
        self._closing = True
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

    def upload_file(self) -> None:
        if (
            self.api is None
            or not self.api.authenticated
            or self._file_task_pending
        ):
            return
        selected = filedialog.askopenfilename(
            title="Choose a file to upload",
            parent=self.root,
        )
        if not selected:
            return

        source = Path(selected)
        validation_error = validate_upload_source(source)
        if validation_error is not None:
            messagebox.showerror(
                "Cannot upload file",
                validation_error,
                parent=self.root,
            )
            return
        filename = source.name
        api = self.api
        self._file_task_pending = True
        self._active_transfer = ("Upload", filename)
        self.connection_view.set_state(connected=True, busy=True)
        self.file_view.set_enabled(False)
        self.transfer_view.start("Uploading", filename)
        self.status.set(f"Uploading {filename}…")

        def progress(done: int, total: int, percent: int) -> None:
            self.worker.emit_progress(
                UPLOAD_TASK,
                TransferProgress("Uploading", filename, done, total, percent),
            )

        self.worker.submit(
            UPLOAD_TASK,
            lambda: api.upload_file(
                source,
                filename,
                progress=progress,
            ),
        )

    def cancel_transfer(self) -> None:
        if self.api is None or self._active_transfer is None:
            return
        action, filename = self._active_transfer
        task_name = transfer_task_name(action)
        if task_name is None or self._cancel_requested is not None:
            return

        self._cancel_requested = task_name
        self.transfer_view.set_cancel_enabled(False)
        self.connection_view.set_state(connected=True, busy=True)
        self.file_view.set_enabled(False)
        self.status.set(f"Cancelling {filename}...")
        self.api.close(abort=True)

    def download_file(self) -> None:
        if (
            self.api is None
            or not self.api.authenticated
            or self._file_task_pending
        ):
            return
        filename = self.file_view.selected_filename()
        if filename is None:
            messagebox.showwarning(
                "Choose a file",
                "Select a remote file to download.",
                parent=self.root,
            )
            return
        selected = filedialog.asksaveasfilename(
            title="Save downloaded file",
            initialfile=filename,
            initialdir=str(self.api.config.client.download_directory),
            confirmoverwrite=False,
            parent=self.root,
        )
        if not selected:
            return

        destination = Path(selected)
        validation_error = validate_download_destination(destination)
        if validation_error is not None:
            messagebox.showerror(
                "Cannot save download",
                validation_error,
                parent=self.root,
            )
            return
        api = self.api
        self._file_task_pending = True
        self._active_transfer = ("Download", filename)
        self.connection_view.set_state(connected=True, busy=True)
        self.file_view.set_enabled(False)
        self.transfer_view.start("Downloading", filename)
        self.status.set(f"Downloading {filename}...")

        def progress(done: int, total: int, percent: int) -> None:
            self.worker.emit_progress(
                DOWNLOAD_TASK,
                TransferProgress("Downloading", filename, done, total, percent),
            )

        self.worker.submit(
            DOWNLOAD_TASK,
            lambda: api.download_file(
                filename,
                destination=destination,
                progress=progress,
            ),
        )

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
            if event.task_name == self._cancel_requested:
                self._handle_cancelled()
                return
            self._handle_failure(event.task_name, event.error)
            return
        if event.kind is UiEventKind.TRANSFER_PROGRESS:
            self._handle_transfer_progress(event.payload)
            return
        if event.kind is UiEventKind.TASK_COMPLETED:
            if event.task_name == self._cancel_requested:
                self._cancel_requested = None
            if event.task_name == CONNECT_TASK:
                self._handle_connected()
            elif event.task_name == DISCONNECT_TASK:
                self._handle_disconnected()
            elif event.task_name == REFRESH_TASK:
                self._handle_refreshed(event.payload)
            elif event.task_name == UPLOAD_TASK:
                self._handle_uploaded(event.payload)
            elif event.task_name == DOWNLOAD_TASK:
                self._handle_downloaded(event.payload)

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

    def _handle_transfer_progress(self, payload: object | None) -> None:
        if self._cancel_requested is not None or not isinstance(
            payload, TransferProgress
        ):
            return
        self.transfer_view.update_progress(
            payload.action,
            payload.filename,
            payload.done,
            payload.total,
            payload.percent,
        )

    def _handle_uploaded(self, payload: object | None) -> None:
        self._file_task_pending = False
        if not isinstance(payload, UploadResult):
            self._handle_file_failure(
                UPLOAD_TASK,
                RuntimeError("worker returned an invalid upload result"),
            )
            return
        self.connection_view.set_state(connected=True)
        self.file_view.set_enabled(True)
        self.transfer_view.complete(
            "Upload",
            payload.remote_filename,
            payload.bytes_sent,
        )
        self._active_transfer = None
        self.status.set(f"Uploaded {payload.remote_filename}")
        messagebox.showinfo(
            "Upload complete",
            f"Uploaded {payload.remote_filename} ({payload.bytes_sent:,} bytes).",
            parent=self.root,
        )
        self.refresh_files()

    def _handle_downloaded(self, payload: object | None) -> None:
        self._file_task_pending = False
        if not isinstance(payload, DownloadResult):
            self._handle_file_failure(
                DOWNLOAD_TASK,
                RuntimeError("worker returned an invalid download result"),
            )
            return
        self.connection_view.set_state(connected=True)
        self.file_view.set_enabled(True)
        self.transfer_view.complete(
            "Download",
            payload.path.name,
            payload.bytes_received,
        )
        self._active_transfer = None
        self.status.set(f"Downloaded {payload.path.name}")
        messagebox.showinfo(
            "Download complete",
            (
                f"Saved {payload.path.name} "
                f"({payload.bytes_received:,} bytes) to:\n{payload.path}"
            ),
            parent=self.root,
        )

    def _handle_disconnected(self) -> None:
        self.api = None
        self._file_task_pending = False
        self._active_transfer = None
        self._cancel_requested = None
        self.connection_view.set_state(connected=False)
        self.file_view.set_enabled(False)
        self.file_view.replace_files(())
        self.transfer_view.reset()
        self.status.set("Disconnected")

    def _handle_cancelled(self) -> None:
        action, filename = self._active_transfer or ("Transfer", "file")
        self._file_task_pending = False
        self._active_transfer = None
        self._cancel_requested = None
        if self.api is not None:
            self.api.close(abort=True)
        self.api = None
        self.connection_view.set_state(connected=False)
        self.file_view.set_enabled(False)
        self.file_view.replace_files(())
        self.transfer_view.cancelled(action, filename)
        self.status.set(f"{action} cancelled — reconnect to continue")

    def _handle_failure(self, task_name: str, error: Exception | None) -> None:
        if task_name in {REFRESH_TASK, UPLOAD_TASK, DOWNLOAD_TASK}:
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
        if task_name in {UPLOAD_TASK, DOWNLOAD_TASK}:
            default_action = "Upload" if task_name == UPLOAD_TASK else "Download"
            action, filename = self._active_transfer or (default_action, "file")
            self.transfer_view.fail(action, filename, message)
            self._active_transfer = None
        messagebox.showerror(
            f"{task_name.capitalize()} failed",
            message,
            parent=self.root,
        )

    def _refresh_shortcut(self, _event: tk.Event[tk.Misc]) -> str:
        self.refresh_files()
        return "break"


def connection_config(base: AppConfig, host: str, port: int) -> AppConfig:
    """Return a connection-specific config without mutating shared defaults."""

    return replace(
        base,
        client=replace(base.client, server_address=host, server_port=port),
    )


def transfer_task_name(action: str) -> str | None:
    return {
        "Upload": UPLOAD_TASK,
        "Download": DOWNLOAD_TASK,
    }.get(action)


def validate_upload_source(path: Path) -> str | None:
    try:
        if not path.exists():
            return "The selected file no longer exists. Choose it again."
        if not path.is_file():
            return "The selected path is not a regular file."
        path.stat()
    except OSError as error:
        return f"The selected file cannot be read: {error}"
    return None


def validate_download_destination(path: Path) -> str | None:
    try:
        if path.exists():
            return "A file or folder already exists at that location. Choose a new name."
        parent = path.parent
        if parent.exists() and not parent.is_dir():
            return "The selected destination folder is not a directory."
    except OSError as error:
        return f"The destination cannot be inspected: {error}"
    return None


def connection_error_message(error: Exception | None) -> str:
    if error is None:
        return "unknown connection error"
    if isinstance(error, (AuthenticationError, ProtocolError)):
        friendly = {
            ErrorCode.SERVER_BUSY: "The server already has 10 active clients. Try again later.",
            ErrorCode.USERNAME_IN_USE: (
                "That username is already connected. Choose another username."
            ),
            ErrorCode.INVALID_USERNAME: "The username is not accepted by the server.",
            ErrorCode.FILE_EXISTS: "A file with that name already exists.",
            ErrorCode.FILE_NOT_FOUND: "The requested remote file no longer exists.",
            ErrorCode.ACCESS_DENIED: "Access to that file or location was denied.",
            ErrorCode.CHECKSUM_MISMATCH: (
                "Checksum verification failed. The incomplete result was not published."
            ),
            ErrorCode.RESUME_METADATA_MISMATCH: (
                "The partial file does not match the remote transfer metadata."
            ),
            ErrorCode.TRANSFER_IN_PROGRESS: (
                "Another client is currently transferring the same file."
            ),
        }.get(error.code)
        if friendly is not None:
            return friendly
        return str(error)
    if isinstance(error, (SessionError, OSError, TimeoutError)):
        return str(error)
    return f"unexpected error: {error}"


def main() -> int:
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
