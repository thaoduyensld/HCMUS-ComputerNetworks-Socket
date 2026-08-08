"""Settings page for appearance and remote-file presentation."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from ..config import AppConfig


class SettingsView(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        config: AppConfig,
        on_theme_change: Callable[[str], None],
        on_layout_change: Callable[[str], None],
    ) -> None:
        super().__init__(master, style="App.TFrame", padding=(18, 18, 18, 10))
        self.theme = tk.StringVar(value="light")
        self.layout = tk.StringVar(value="list")

        title = ttk.Frame(self, style="App.TFrame")
        title.pack(fill="x", pady=(0, 14))
        ttk.Label(title, text="Settings", style="Status.TLabel").pack(anchor="w")

        appearance = ttk.Frame(self, style="Card.TFrame", padding=22)
        appearance.pack(fill="x", pady=(0, 14))
        ttk.Label(appearance, text="Appearance", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            appearance,
            text="Switch the complete application palette immediately.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 12))
        theme_buttons = ttk.Frame(appearance, style="CardBody.TFrame")
        theme_buttons.pack(anchor="w")
        for value, label in (("light", "☀  Light"), ("dark", "☾  Dark")):
            ttk.Radiobutton(
                theme_buttons,
                text=label,
                value=value,
                variable=self.theme,
                command=lambda selected=value: on_theme_change(selected),
            ).pack(side="left", padx=(0, 18))

        files = ttk.Frame(self, style="Card.TFrame", padding=22)
        files.pack(fill="x", pady=(0, 14))
        ttk.Label(files, text="Remote file layout", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            files,
            text="Choose a detailed table or compact visual cards.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 12))
        layout_buttons = ttk.Frame(files, style="CardBody.TFrame")
        layout_buttons.pack(anchor="w")
        for value, label in (("list", "☷  List"), ("grid", "▦  Grid")):
            ttk.Radiobutton(
                layout_buttons,
                text=label,
                value=value,
                variable=self.layout,
                command=lambda selected=value: on_layout_change(selected),
            ).pack(side="left", padx=(0, 18))

        connection = ttk.Frame(self, style="Card.TFrame", padding=22)
        connection.pack(fill="x")
        ttk.Label(connection, text="Current defaults", style="Title.TLabel").pack(anchor="w")
        details = (
            f"Server: {config.client.server_address}:{config.client.server_port}\n"
            f"Downloads: {config.client.download_directory}\n"
            f"Maximum clients: {config.server.max_clients}\n"
            "Per-client bandwidth: "
            f"{config.network.bandwidth_limit_kib_per_second} KiB/s"
        )
        ttk.Label(connection, text=details, style="Subtitle.TLabel", justify="left").pack(
            anchor="w", pady=(8, 0)
        )

    def set_theme(self, mode: str) -> None:
        self.theme.set(mode)

    def set_layout(self, layout: str) -> None:
        self.layout.set(layout)
