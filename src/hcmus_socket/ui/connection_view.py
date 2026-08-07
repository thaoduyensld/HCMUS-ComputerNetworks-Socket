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
        self.host = tk.StringVar(value="127.0.0.1")
        self.port = tk.StringVar(value="4567")
        self.username = tk.StringVar()

        header = ttk.Frame(self, style="CardBody.TFrame")
        header.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 16))
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

        self.host_entry = self._field("Server (IP Address)", self.host, 0, 22)
        self.port_entry = self._field("Port", self.port, 1, 8)
        self.username_entry = self._field("Username", self.username, 2, 18)

        self.connect_button = ttk.Button(
            self,
            text="↗  Connect",
            command=on_connect,
            style="Accent.TButton",
        )
        self.connect_button.grid(row=2, column=3, padx=(4, 10), pady=(5, 0))
        self.disconnect_button = ttk.Button(
            self,
            text="↪  Disconnect",
            command=on_disconnect,
            state="disabled",
            style="Danger.TButton",
        )
        self.disconnect_button.grid(row=2, column=4, pady=(5, 0))
        for column in range(3):
            self.columnconfigure(column, weight=1)

    def _field(
        self,
        label: str,
        variable: tk.StringVar,
        column: int,
        width: int,
    ) -> ttk.Entry:
        ttk.Label(self, text=label, style="Field.TLabel").grid(
            row=1, column=column, sticky="w"
        )
        entry = ttk.Entry(
            self,
            textvariable=variable,
            width=width,
            style="Modern.TEntry",
        )
        entry.grid(row=2, column=column, padx=(0, 14), pady=(5, 0), sticky="ew")
        return entry

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
        entry_state = "disabled" if connected else "normal"
        for entry in (self.host_entry, self.port_entry, self.username_entry):
            entry.configure(state=entry_state)
        self.connect_button.configure(state="disabled" if connected else "normal")
        self.disconnect_button.configure(state="normal" if connected else "disabled")
        self.connection_badge.configure(
            text="●  Connected" if connected else "●  Disconnected",
            style="Success.TLabel" if connected else "Offline.TLabel",
        )

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
