"""In-application project and protocol information page."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class AboutView(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, style="App.TFrame", padding=(18, 18, 18, 10))
        card = ttk.Frame(self, style="Card.TFrame", padding=30)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text="☁", style="Title.TLabel", font=("Segoe UI Symbol", 38)).pack()
        ttk.Label(card, text="HCMUS Socket File Client", style="Title.TLabel").pack(
            pady=(10, 4)
        )
        ttk.Label(
            card,
            text="Protocol v2 • Python • Tkinter",
            style="Subtitle.TLabel",
        ).pack()
        ttk.Separator(card, orient="horizontal").pack(fill="x", pady=24)
        features = (
            "Binary length-prefixed framing\n"
            "Per-user storage namespaces\n"
            "Concurrent clients and SERVER_BUSY capacity control\n"
            "Resumable Upload and Download with SHA-256 verification\n"
            "Per-session token-bucket bandwidth throttling\n"
            "Thread-safe registry, filename locks, and JSON logging"
        )
        ttk.Label(
            card,
            text=features,
            style="Subtitle.TLabel",
            justify="center",
        ).pack()
        ttk.Label(
            card,
            text="Computer Networks • HCMUS • Phase 2",
            style="Subtitle.TLabel",
        ).pack(side="bottom", pady=(20, 0))
