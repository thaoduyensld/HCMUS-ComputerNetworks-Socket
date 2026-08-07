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
        self.tree.grid(row=0, column=0, columnspan=3, sticky="nsew")
        scrollbar.grid(row=0, column=3, sticky="ns")

        self.refresh_button = ttk.Button(self, text="Refresh", command=on_refresh)
        self.upload_button = ttk.Button(self, text="Upload…", command=on_upload)
        self.download_button = ttk.Button(self, text="Download", command=on_download)
        self.refresh_button.grid(row=1, column=0, pady=(10, 0), sticky="w")
        self.upload_button.grid(row=1, column=1, pady=(10, 0))
        self.download_button.grid(row=1, column=2, pady=(10, 0), sticky="e")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(2, weight=1)
        self.set_enabled(False)

    def replace_files(self, entries: Iterable[FileEntry]) -> None:
        self.tree.delete(*self.tree.get_children())
        for entry in entries:
            self.tree.insert("", "end", values=(entry.filename, entry.file_size))

    def selected_filename(self) -> str | None:
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        return str(values[0]) if values else None

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.refresh_button, self.upload_button, self.download_button):
            button.configure(state=state)
