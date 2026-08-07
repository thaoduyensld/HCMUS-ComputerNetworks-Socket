"""Desktop application shell for the HCMUS socket client."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .connection_view import ConnectionView
from .file_view import FileView
from .transfer_view import TransferView
from .worker import BackgroundWorker, UiEvent


class DesktopApp:
    """Compose the desktop views and own their background worker."""

    POLL_INTERVAL_MS = 50

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.worker = BackgroundWorker()
        self.status = tk.StringVar(value="Disconnected")

        root.title("HCMUS Socket File Client")
        root.geometry("760x560")
        root.minsize(640, 460)

        container = ttk.Frame(root, padding=12)
        container.pack(fill="both", expand=True)
        self.connection_view = ConnectionView(
            container,
            on_connect=self._not_integrated,
            on_disconnect=self._not_integrated,
        )
        self.file_view = FileView(
            container,
            on_refresh=self._not_integrated,
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
        root.after(self.POLL_INTERVAL_MS, self._poll_worker)

    def close(self) -> None:
        self.worker.close()
        self.root.destroy()

    def _poll_worker(self) -> None:
        event = self.worker.poll()
        while event is not None:
            self.handle_event(event)
            event = self.worker.poll()
        if not self.worker.closed:
            self.root.after(self.POLL_INTERVAL_MS, self._poll_worker)

    def handle_event(self, event: UiEvent[object]) -> None:
        """Handle worker events; networking-specific mapping is added next."""

        self.status.set(event.task_name)

    def _not_integrated(self) -> None:
        messagebox.showinfo(
            "Desktop UI",
            "Networking actions will be connected in the next implementation step.",
            parent=self.root,
        )


def main() -> int:
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
