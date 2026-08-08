"""Modern remote-file browser card with list and grid layouts."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import tkinter as tk
from tkinter import ttk

from ..messages import FileEntry


LAYOUTS = frozenset({"list", "grid"})


def normalize_layout(layout: str) -> str:
    if layout not in LAYOUTS:
        raise ValueError("file layout must be 'list' or 'grid'")
    return layout


class FileView(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_refresh: Callable[[], None],
        on_upload: Callable[[], None],
        on_download: Callable[[], None],
        on_layout_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, style="Card.TFrame", padding=12)
        self._enabled = False
        self._on_download = on_download
        self._on_layout_change = on_layout_change
        self._entries: tuple[FileEntry, ...] = ()
        self._selected_filename: str | None = None
        self._compact = False
        self._grid_columns = 3
        self.layout = "list"
        self.summary = tk.StringVar(value="0 files")

        header = ttk.Frame(self, style="CardBody.TFrame")
        self.header = header
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 10))
        ttk.Label(header, text="▣  Remote Files", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Browse and manage files on the remote server",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        controls = ttk.Frame(header, style="CardBody.TFrame")
        self.controls = controls
        controls.place(relx=1.0, rely=0.0, anchor="ne")
        self.refresh_button = ttk.Button(
            controls,
            text="↻  Refresh",
            command=on_refresh,
            style="Outline.TButton",
        )
        self.refresh_button.pack(side="left", padx=(0, 8))
        self.list_button = ttk.Button(
            controls,
            text="☷",
            command=lambda: self.set_layout("list"),
            style="Accent.TButton",
            width=3,
        )
        self.list_button.pack(side="left", padx=(0, 4))
        self.grid_button = ttk.Button(
            controls,
            text="▦",
            command=lambda: self.set_layout("grid"),
            style="Outline.TButton",
            width=3,
        )
        self.grid_button.pack(side="left")

        self.browser = ttk.Frame(self, style="CardBody.TFrame")
        self.browser.grid(row=1, column=0, sticky="nsew")
        self.browser.rowconfigure(0, weight=1)
        self.browser.columnconfigure(0, weight=1)

        self.table = ttk.Frame(self.browser, style="CardBody.TFrame")
        self.tree = ttk.Treeview(
            self.table,
            columns=("filename", "size"),
            show="headings",
            selectmode="browse",
            style="Modern.Treeview",
            height=9,
        )
        self.tree.heading("filename", text="Filename")
        self.tree.heading("size", text="Size")
        self.tree.column("filename", minwidth=180, width=600, stretch=True)
        self.tree.column("size", minwidth=110, width=140, anchor="e", stretch=False)
        scrollbar = ttk.Scrollbar(self.table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.table.rowconfigure(0, weight=1)
        self.table.columnconfigure(0, weight=1)

        self.grid_canvas = tk.Canvas(
            self.browser,
            highlightthickness=0,
            borderwidth=0,
        )
        self.grid_inner = ttk.Frame(self.grid_canvas, style="CardBody.TFrame")
        self.grid_scrollbar = ttk.Scrollbar(
            self.browser,
            orient="vertical",
            command=self.grid_canvas.yview,
        )
        self.grid_canvas.configure(yscrollcommand=self.grid_scrollbar.set)
        self._grid_window = self.grid_canvas.create_window(
            (0, 0), window=self.grid_inner, anchor="nw"
        )
        self.grid_inner.bind("<Configure>", self._update_grid_scrollregion)
        self.grid_canvas.bind("<Configure>", self._resize_grid_window)

        self.empty_message = tk.StringVar(
            value="No files to display\nConnect to a server and refresh the file list."
        )
        self.empty_label = ttk.Label(
            self.browser,
            textvariable=self.empty_message,
            justify="center",
            style="Subtitle.TLabel",
            font=("Segoe UI Semibold", 11),
        )

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
        ttk.Label(footer, textvariable=self.summary, style="Summary.TLabel").pack(
            side="left"
        )
        self.download_button.pack(side="right")
        self.upload_button.pack(side="right", padx=(0, 10))

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.set_layout("list", notify=False)
        self.set_enabled(False)

    def replace_files(self, entries: Iterable[FileEntry]) -> None:
        self._entries = tuple(sorted(entries, key=lambda entry: entry.filename.casefold()))
        self._selected_filename = None
        self.tree.delete(*self.tree.get_children())
        for entry in self._entries:
            self.tree.insert("", "end", values=(entry.filename, format_size(entry.file_size)))
        self._render_grid()
        suffix = "file" if len(self._entries) == 1 else "files"
        self.summary.set(f"{len(self._entries)} {suffix}")
        self._update_empty_state()
        self._update_download_state()

    def selected_filename(self) -> str | None:
        if self.layout == "grid":
            return self._selected_filename
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        return str(values[0]) if values else None

    def set_layout(self, layout: str, *, notify: bool = True) -> None:
        selected = self.selected_filename() if hasattr(self, "tree") else None
        self.layout = normalize_layout(layout)
        self._selected_filename = selected
        self.table.grid_forget()
        self.grid_canvas.grid_forget()
        self.grid_scrollbar.grid_forget()
        if self.layout == "list":
            self.table.grid(row=0, column=0, sticky="nsew")
        else:
            self.grid_canvas.grid(row=0, column=0, sticky="nsew")
            self.grid_scrollbar.grid(row=0, column=1, sticky="ns")
            self._render_grid()
        self.list_button.configure(
            style="Accent.TButton" if self.layout == "list" else "Outline.TButton"
        )
        self.grid_button.configure(
            style="Accent.TButton" if self.layout == "grid" else "Outline.TButton"
        )
        self._update_empty_state()
        self._update_download_state()
        if notify and self._on_layout_change is not None:
            self._on_layout_change(self.layout)

    def apply_palette(self, colors: dict[str, str]) -> None:
        self.grid_canvas.configure(background=colors["card"])

    def set_compact(self, compact: bool) -> None:
        """Adapt headers, table columns, and cards for a narrow window."""

        if self._compact == compact:
            return
        self._compact = compact
        self._grid_columns = 1 if compact else 3
        if compact:
            self.configure(padding=8)
            self.controls.place_forget()
            self.controls.pack(fill="x", pady=(8, 0))
            self.tree.configure(height=3)
            self.tree.column("filename", minwidth=120, width=220, stretch=True)
            self.tree.column("size", minwidth=70, width=85, stretch=False)
            self.upload_button.configure(text="Upload...")
            self.download_button.configure(text="Download")
        else:
            self.configure(padding=12)
            self.controls.pack_forget()
            self.controls.place(relx=1.0, rely=0.0, anchor="ne")
            self.tree.configure(height=9)
            self.tree.column("filename", minwidth=180, width=600, stretch=True)
            self.tree.column("size", minwidth=110, width=140, stretch=False)
            self.upload_button.configure(text="☁  Upload...")
            self.download_button.configure(text="⇩  Download")
        self._render_grid()
        self._update_empty_state()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        self.refresh_button.configure(state=state)
        self.upload_button.configure(state=state)
        if not enabled and not self._entries:
            self.empty_message.set(
                "No files to display\nConnect to a server and refresh the file list."
            )
        self._update_download_state()

    def _render_grid(self) -> None:
        for child in self.grid_inner.winfo_children():
            child.destroy()
        for column in range(3):
            self.grid_inner.columnconfigure(column, weight=0, uniform="")
        for column in range(self._grid_columns):
            self.grid_inner.columnconfigure(column, weight=1, uniform="files")
        for index, entry in enumerate(self._entries):
            style = (
                "ActiveFileCard.TButton"
                if entry.filename == self._selected_filename
                else "FileCard.TButton"
            )
            button = ttk.Button(
                self.grid_inner,
                text=f"▣\n{entry.filename}\n{format_size(entry.file_size)}",
                style=style,
                command=lambda name=entry.filename: self._select_grid_file(name),
            )
            button.grid(
                row=index // self._grid_columns,
                column=index % self._grid_columns,
                sticky="nsew",
                padx=8,
                pady=8,
                ipady=14,
            )
            button.bind("<Double-1>", self._on_grid_double_click)

    def _select_grid_file(self, filename: str) -> None:
        self._selected_filename = filename
        self._render_grid()
        self._update_download_state()

    def _on_selection_changed(self, _event: tk.Event[tk.Misc]) -> None:
        self._selected_filename = self.selected_filename()
        self._update_download_state()

    def _on_double_click(self, _event: tk.Event[tk.Misc]) -> None:
        if self._enabled and self.selected_filename() is not None:
            self._on_download()

    def _on_grid_double_click(self, _event: tk.Event[tk.Misc]) -> None:
        if self._enabled and self._selected_filename is not None:
            self._on_download()

    def _update_empty_state(self) -> None:
        self.empty_label.place_forget()
        if self._entries:
            return
        if self._enabled:
            self.empty_message.set(
                "No files to display\nUpload a file or refresh the remote file list."
            )
        self.empty_label.place(relx=0.5, rely=0.52, anchor="center")

    def _update_download_state(self) -> None:
        enabled = self._enabled and self.selected_filename() is not None
        self.download_button.configure(state="normal" if enabled else "disabled")

    def _update_grid_scrollregion(self, _event: tk.Event[tk.Misc]) -> None:
        self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all"))

    def _resize_grid_window(self, event: tk.Event[tk.Misc]) -> None:
        self.grid_canvas.itemconfigure(self._grid_window, width=event.width)


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
