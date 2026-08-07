"""Connection controls for the desktop client."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk


class ConnectionView(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_connect: Callable[[], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        super().__init__(master, text="Connection", padding=12)
        self.host = tk.StringVar(value="127.0.0.1")
        self.port = tk.StringVar(value="4567")
        self.username = tk.StringVar()

        ttk.Label(self, text="Server").grid(row=0, column=0, sticky="w")
        self.host_entry = ttk.Entry(self, textvariable=self.host, width=22)
        self.host_entry.grid(row=1, column=0, padx=(0, 8), sticky="ew")
        ttk.Label(self, text="Port").grid(row=0, column=1, sticky="w")
        self.port_entry = ttk.Entry(self, textvariable=self.port, width=8)
        self.port_entry.grid(row=1, column=1, padx=(0, 8), sticky="ew")
        ttk.Label(self, text="Username").grid(row=0, column=2, sticky="w")
        self.username_entry = ttk.Entry(self, textvariable=self.username, width=18)
        self.username_entry.grid(row=1, column=2, padx=(0, 12), sticky="ew")

        self.connect_button = ttk.Button(self, text="Connect", command=on_connect)
        self.connect_button.grid(row=1, column=3, padx=(0, 8))
        self.disconnect_button = ttk.Button(
            self,
            text="Disconnect",
            command=on_disconnect,
            state="disabled",
        )
        self.disconnect_button.grid(row=1, column=4)
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
        entry_state = "disabled" if connected else "normal"
        for entry in (self.host_entry, self.port_entry, self.username_entry):
            entry.configure(state=entry_state)
        self.connect_button.configure(state="disabled" if connected else "normal")
        self.disconnect_button.configure(state="normal" if connected else "disabled")

    def set_busy(self, busy: bool) -> None:
        if busy:
            self.connect_button.configure(state="disabled")
            self.disconnect_button.configure(state="disabled")
