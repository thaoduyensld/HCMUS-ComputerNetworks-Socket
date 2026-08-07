"""Transfer progress and status widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class TransferView(ttk.LabelFrame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, text="Transfer", padding=12)
        self.description = tk.StringVar(value="No active transfer")
        self.detail = tk.StringVar(value="")
        self.percent = tk.IntVar(value=0)

        ttk.Label(self, textvariable=self.description).grid(row=0, column=0, sticky="w")
        ttk.Label(self, textvariable=self.detail).grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(
            self,
            variable=self.percent,
            maximum=100,
            mode="determinate",
        )
        self.progress.grid(row=1, column=0, columnspan=2, pady=(8, 0), sticky="ew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

    def reset(self) -> None:
        self.description.set("No active transfer")
        self.detail.set("")
        self.percent.set(0)

    def update_progress(
        self,
        action: str,
        filename: str,
        done: int,
        total: int,
        percent: int,
    ) -> None:
        self.description.set(f"{action}: {filename}")
        self.detail.set(f"{done:,} / {total:,} bytes ({percent}%)")
        self.percent.set(max(0, min(100, percent)))
