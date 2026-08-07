"""Modern remote-file browser card."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import tkinter as tk
from tkinter import ttk

from ..messages import FileEntry


class FileView(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_refresh: Callable[[], None],
        on_upload: Callable[[], None],
        on_download: Callable[[], None],
    ) -> None:
        super().__init__(master, style="Card.TFrame", padding=12)
        self._enabled = False
        self._on_download = on_download
        self.summary = tk.StringVar(value="0 files")

        header = ttk.Frame(self, style="CardBody.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 10))
        ttk.Label(header, text="▣  Remote Files", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Browse and manage files on the remote server",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        self.refresh_button = ttk.Button(
            header,
            text="↻  Refresh",
            command=on_refresh,
            style="Outline.TButton",
        )
        self.refresh_button.place(relx=1.0, rely=0.0, anchor="ne")

        table = ttk.Frame(self, style="CardBody.TFrame")
        table.grid(row=1, column=0, sticky="nsew")
        self.tree = ttk.Treeview(
            table,
            columns=("filename", "size"),
            show="headings",
            selectmode="browse",
            style="Modern.Treeview",
            height=9,
        )
        self.tree.heading("filename", text="Filename")
        self.tree.heading("size", text="Size (bytes)")
        self.tree.column("filename", minwidth=180, width=600, stretch=True)
        self.tree.column("size", minwidth=110, width=140, anchor="e", stretch=False)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)

        self.empty_message = tk.StringVar(
            value="No files to display\nConnect to a server and refresh the file list."
        )
        self.empty_label = ttk.Label(
            table,
            textvariable=self.empty_message,
            justify="center",
            style="Subtitle.TLabel",
            font=("Segoe UI Semibold", 11),
        )
        self.empty_label.place(relx=0.5, rely=0.52, anchor="center")

        footer = ttk.Frame(self, style="CardBody.TFrame")
        footer.grid(row=2, column=0, sticky="ew", padx=4, pady=(10, 0))
        self.upload_button = ttk.Button(
            footer,
            text="☁  Upload...",
            command=on_upload,
            style="Outline.TButton",
        )
        self.download_button = ttk.Button(
            footer,
            text="⇩  Download",
            command=on_download,
            style="Accent.TButton",
        )
        ttk.Label(
            footer,
            textvariable=self.summary,
            background="#FFFFFF",
            foreground="#159447",
            font=("Segoe UI Semibold", 9),
        ).pack(side="left")
        self.download_button.pack(side="right")
        self.upload_button.pack(side="right", padx=(0, 10))

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.set_enabled(False)

    def replace_files(self, entries: Iterable[FileEntry]) -> None:
        ordered = tuple(sorted(entries, key=lambda entry: entry.filename.casefold()))
        self.tree.delete(*self.tree.get_children())
        for entry in ordered:
            self.tree.insert(
                "", "end", values=(entry.filename, format_size(entry.file_size))
            )
        suffix = "file" if len(ordered) == 1 else "files"
        self.summary.set(f"{len(ordered)} {suffix}")
        if ordered:
            self.empty_label.place_forget()
        else:
            self.empty_message.set(
                "No files to display\nUpload a file or refresh the remote file list."
            )
            self.empty_label.place(relx=0.5, rely=0.52, anchor="center")
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
        if not enabled and not self.tree.get_children():
            self.empty_message.set(
                "No files to display\nConnect to a server and refresh the file list."
            )
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
