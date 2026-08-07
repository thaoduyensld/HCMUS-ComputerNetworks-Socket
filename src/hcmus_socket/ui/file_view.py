"""Remote-file browser widgets."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import tkinter as tk
from tkinter import ttk

from ..messages import FileEntry


class FileView(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_refresh: Callable[[], None],
        on_upload: Callable[[], None],
        on_download: Callable[[], None],
    ) -> None:
        super().__init__(master, text="Remote files", padding=12)
        self._enabled = False
        self.summary = tk.StringVar(value="0 files")
        self.tree = ttk.Treeview(
            self,
            columns=("filename", "size"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("filename", text="Filename")
        self.tree.heading("size", text="Size (bytes)")
        self.tree.column("filename", minwidth=180, width=420, stretch=True)
        self.tree.column("size", minwidth=100, width=130, anchor="e", stretch=False)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.grid(row=0, column=0, columnspan=3, sticky="nsew")
        scrollbar.grid(row=0, column=3, sticky="ns")

        self.refresh_button = ttk.Button(self, text="Refresh", command=on_refresh)
        self.upload_button = ttk.Button(self, text="Upload…", command=on_upload)
        self.download_button = ttk.Button(self, text="Download", command=on_download)
        self.refresh_button.grid(row=1, column=0, pady=(10, 0), sticky="w")
        self.upload_button.grid(row=1, column=1, pady=(10, 0))
        self.download_button.grid(row=1, column=2, pady=(10, 0), sticky="e")
        ttk.Label(self, textvariable=self.summary).grid(
            row=2,
            column=0,
            columnspan=3,
            pady=(8, 0),
            sticky="w",
        )
        self._on_download = on_download
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(2, weight=1)
        self.set_enabled(False)

    def replace_files(self, entries: Iterable[FileEntry]) -> None:
        ordered = tuple(sorted(entries, key=lambda entry: entry.filename.casefold()))
        self.tree.delete(*self.tree.get_children())
        for entry in ordered:
            self.tree.insert(
                "",
                "end",
                values=(entry.filename, format_size(entry.file_size)),
            )
        suffix = "file" if len(ordered) == 1 else "files"
        self.summary.set(f"{len(ordered)} {suffix}")
        self._update_download_state()

    def selected_filename(self) -> str | None:
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        return str(values[0]) if values else None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        self.refresh_button.configure(state=state)
        self.upload_button.configure(state=state)
        self._update_download_state()

    def _on_selection_changed(self, _event: tk.Event[tk.Misc]) -> None:
        self._update_download_state()

    def _on_double_click(self, _event: tk.Event[tk.Misc]) -> None:
        if self._enabled and self.selected_filename() is not None:
            self._on_download()

    def _update_download_state(self) -> None:
        enabled = self._enabled and self.selected_filename() is not None
        self.download_button.configure(state="normal" if enabled else "disabled")


def format_size(size: int) -> str:
    """Format an exact byte count for compact display."""

    if size < 0:
        raise ValueError("size must not be negative")
    value = float(size)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.2f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")
