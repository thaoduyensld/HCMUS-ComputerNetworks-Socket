"""Modern connection card for the desktop client."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk


class ConnectionView(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_connect: Callable[[], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        super().__init__(master, style="Card.TFrame", padding=20)
        self._compact = False
        self._connected = False
        self.host = tk.StringVar(value="127.0.0.1")
        self.port = tk.StringVar(value="4567")
        self.username = tk.StringVar()

        header = ttk.Frame(self, style="CardBody.TFrame")
        self.header = header
        ttk.Label(header, text="◉  Connection", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Connect to a server to start transferring files",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        self.connection_badge = ttk.Label(
            header, text="●  Disconnected", style="Offline.TLabel"
        )
        self.connection_badge.place(relx=1.0, rely=0.0, anchor="ne")

        self.host_label, self.host_entry = self._field(
            "Server (IP Address)", self.host, 22
        )
        self.port_label, self.port_entry = self._field("Port", self.port, 8)
        self.username_label, self.username_entry = self._field(
            "Username", self.username, 18
        )

        self.connect_button = ttk.Button(
            self,
            text="↗  Connect",
            command=on_connect,
            style="Accent.TButton",
        )
        self.disconnect_button = ttk.Button(
            self,
            text="↪  Disconnect",
            command=on_disconnect,
            state="disabled",
            style="Danger.TButton",
        )
        self._layout_normal()

    def _field(
        self,
        label: str,
        variable: tk.StringVar,
        width: int,
    ) -> tuple[ttk.Label, ttk.Entry]:
        field_label = ttk.Label(self, text=label, style="Field.TLabel")
        entry = ttk.Entry(
            self,
            textvariable=variable,
            width=width,
            style="Modern.TEntry",
        )
        return field_label, entry

    def set_compact(self, compact: bool) -> None:
        """Switch between wide and vertically stacked connection controls."""

        if self._compact == compact:
            return
        self._compact = compact
        if compact:
            if self._connected:
                self._layout_compact_connected()
            else:
                self._layout_compact()
        else:
            self._layout_normal()

    def _clear_layout(self) -> None:
        for widget in (
            self.header,
            self.host_label,
            self.host_entry,
            self.port_label,
            self.port_entry,
            self.username_label,
            self.username_entry,
            self.connect_button,
            self.disconnect_button,
        ):
            widget.grid_forget()
        for column in range(5):
            self.columnconfigure(column, weight=0)

    def _layout_normal(self) -> None:
        self._clear_layout()
        self.configure(padding=20)
        self.connection_badge.pack_forget()
        self.connection_badge.place(relx=1.0, rely=0.0, anchor="ne")
        self.header.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 16))
        fields = (
            (self.host_label, self.host_entry),
            (self.port_label, self.port_entry),
            (self.username_label, self.username_entry),
        )
        for column, (label, entry) in enumerate(fields):
            label.grid(row=1, column=column, sticky="w")
            entry.grid(row=2, column=column, padx=(0, 14), pady=(5, 0), sticky="ew")
            self.columnconfigure(column, weight=1)
        self.connect_button.grid(row=2, column=3, padx=(4, 10), pady=(5, 0))
        self.disconnect_button.grid(row=2, column=4, pady=(5, 0))

    def _layout_compact(self) -> None:
        self._clear_layout()
        self.configure(padding=12)
        self.connection_badge.pack_forget()
        self.connection_badge.place(relx=1.0, rely=0.0, anchor="ne")
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        fields = (
            (self.host_label, self.host_entry),
            (self.port_label, self.port_entry),
            (self.username_label, self.username_entry),
        )
        for index, (label, entry) in enumerate(fields):
            row = 1 + index * 2
            label.grid(row=row, column=0, columnspan=2, sticky="w")
            entry.grid(
                row=row + 1,
                column=0,
                columnspan=2,
                pady=(4, 8),
                sticky="ew",
            )
        self.connect_button.grid(row=7, column=0, padx=(0, 5), sticky="ew")
        self.disconnect_button.grid(row=7, column=1, padx=(5, 0), sticky="ew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

    def _layout_compact_connected(self) -> None:
        self._clear_layout()
        self.configure(padding=10)
        self.connection_badge.pack_forget()
        self.connection_badge.place(relx=1.0, rely=0.0, anchor="ne")
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.disconnect_button.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)

    def credentials(self) -> tuple[str, int, str]:
        host = self.host.get().strip()
        username = self.username.get().strip()
        try:
            port = int(self.port.get().strip())
        except ValueError as error:
            raise ValueError("port must be a decimal integer") from error
        if not host:
            raise ValueError("server address is required")
        if not 1 <= port <= 65535:
            raise ValueError("port must be from 1 to 65535")
        if not username:
            raise ValueError("username is required")
        return host, port, username

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        entry_state = "disabled" if connected else "normal"
        for entry in (self.host_entry, self.port_entry, self.username_entry):
            entry.configure(state=entry_state)
        self.connect_button.configure(state="disabled" if connected else "normal")
        self.disconnect_button.configure(state="normal" if connected else "disabled")
        self.connection_badge.configure(
            text="●  Connected" if connected else "●  Disconnected",
            style="Success.TLabel" if connected else "Offline.TLabel",
        )
        if self._compact:
            if connected:
                self._layout_compact_connected()
            else:
                self._layout_compact()

    def set_busy(self, busy: bool) -> None:
        if busy:
            for entry in (self.host_entry, self.port_entry, self.username_entry):
                entry.configure(state="disabled")
            self.connect_button.configure(state="disabled")
            self.disconnect_button.configure(state="disabled")

    def set_state(self, *, connected: bool, busy: bool = False) -> None:
        self.set_connected(connected)
        if busy:
            self.set_busy(True)
