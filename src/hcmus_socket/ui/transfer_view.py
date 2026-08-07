"""Transfer progress and status widgets."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk


class TransferView(ttk.LabelFrame):
    def __init__(self, master: tk.Misc, *, on_cancel: Callable[[], None]) -> None:
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
        self.cancel_button = ttk.Button(
            self,
            text="Cancel transfer",
            command=on_cancel,
            state="disabled",
        )
        self.cancel_button.grid(row=2, column=1, pady=(8, 0), sticky="e")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

    def reset(self) -> None:
        self.description.set("No active transfer")
        self.detail.set("")
        self.percent.set(0)
        self.set_cancel_enabled(False)

    def start(self, action: str, filename: str) -> None:
        self.description.set(f"{action}: {filename}")
        self.detail.set("Starting…")
        self.percent.set(0)
        self.set_cancel_enabled(True)

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
        bounded = max(0, min(100, percent))
        self.percent.set(max(self.percent.get(), bounded))

    def complete(self, action: str, filename: str, total: int) -> None:
        self.description.set(f"{action} complete: {filename}")
        self.detail.set(f"{total:,} bytes — checksum verified")
        self.percent.set(100)
        self.set_cancel_enabled(False)

    def fail(self, action: str, filename: str, message: str) -> None:
        self.description.set(f"{action} failed: {filename}")
        self.detail.set(message)
        self.set_cancel_enabled(False)

    def cancelled(self, action: str, filename: str) -> None:
        self.description.set(f"{action} cancelled: {filename}")
        self.detail.set("Reconnect to continue the transfer later")
        self.set_cancel_enabled(False)

    def set_cancel_enabled(self, enabled: bool) -> None:
        self.cancel_button.configure(state="normal" if enabled else "disabled")
