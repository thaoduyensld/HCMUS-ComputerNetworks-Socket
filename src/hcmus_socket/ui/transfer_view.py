"""Modern transfer progress card and UI-only transfer metrics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from time import monotonic
import tkinter as tk
from tkinter import ttk

from .file_view import format_size


@dataclass(frozen=True, slots=True)
class TransferSnapshot:
    bytes_per_second: float
    eta_seconds: float | None
    resumed_from: int


class TransferTracker:
    """Calculate UI-only speed and ETA without affecting transfer callbacks."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._baseline_done: int | None = None
        self._baseline_time: float | None = None

    def update(
        self,
        done: int,
        total: int,
        *,
        now: float | None = None,
    ) -> TransferSnapshot:
        sample_time = monotonic() if now is None else now
        if self._baseline_done is None or self._baseline_time is None:
            self._baseline_done = done
            self._baseline_time = sample_time
            return TransferSnapshot(0.0, None, max(0, done))
        elapsed = max(0.0, sample_time - self._baseline_time)
        transferred = max(0, done - self._baseline_done)
        rate = transferred / elapsed if elapsed > 0 else 0.0
        remaining = max(0, total - done)
        eta = remaining / rate if rate > 0 and remaining > 0 else None
        return TransferSnapshot(rate, eta, max(0, self._baseline_done))


class TransferView(ttk.Frame):
    def __init__(self, master: tk.Misc, *, on_cancel: Callable[[], None]) -> None:
        super().__init__(master, style="Card.TFrame", padding=18)
        self._compact = False
        self.description = tk.StringVar(value="No active transfer")
        self.detail = tk.StringVar(value="")
        self.percent = tk.IntVar(value=0)
        self.tracker = TransferTracker()

        ttk.Label(self, text="➤  Transfer", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self, text="Monitor your file transfers", style="Subtitle.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))
        self.description_label = ttk.Label(
            self,
            textvariable=self.description,
            style="TransferTitle.TLabel",
        )
        self.description_label.grid(row=2, column=0, sticky="w")
        self.detail_label = ttk.Label(
            self, textvariable=self.detail, style="Subtitle.TLabel"
        )
        self.detail_label.grid(row=2, column=1, sticky="e")
        self.progress = ttk.Progressbar(
            self,
            variable=self.percent,
            maximum=100,
            mode="determinate",
            style="Modern.Horizontal.TProgressbar",
        )
        self.progress.grid(row=3, column=0, columnspan=2, pady=(9, 0), sticky="ew")
        self.cancel_button = ttk.Button(
            self,
            text="×  Cancel transfer",
            command=on_cancel,
            state="disabled",
            style="Danger.TButton",
        )
        # Keep the cancellation action in the always-visible header. Putting it
        # below the progress bar made it the first control clipped by short or
        # display-scaled windows.
        self.cancel_button.grid(row=0, column=1, rowspan=2, sticky="e")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

    def set_compact(self, compact: bool) -> None:
        """Place verbose transfer metrics below the title in narrow windows."""

        if self._compact == compact:
            return
        self._compact = compact
        for widget in (
            self.description_label,
            self.detail_label,
            self.progress,
            self.cancel_button,
        ):
            widget.grid_forget()
        if compact:
            self.configure(padding=12)
            self.description_label.grid(row=2, column=0, columnspan=2, sticky="w")
            self.detail_label.configure(wraplength=350, justify="left")
            self.detail_label.grid(
                row=3, column=0, columnspan=2, sticky="w", pady=(3, 0)
            )
            self.progress.grid(
                row=4, column=0, columnspan=2, pady=(8, 0), sticky="ew"
            )
            self.cancel_button.grid(row=0, column=1, rowspan=2, sticky="e")
        else:
            self.configure(padding=18)
            self.description_label.grid(row=2, column=0, sticky="w")
            self.detail_label.configure(wraplength=0, justify="left")
            self.detail_label.grid(row=2, column=1, sticky="e")
            self.progress.grid(
                row=3, column=0, columnspan=2, pady=(9, 0), sticky="ew"
            )
            self.cancel_button.grid(row=0, column=1, rowspan=2, sticky="e")

    def reset(self) -> None:
        self.description.set("No active transfer")
        self.detail.set("")
        self.percent.set(0)
        self.tracker.reset()
        self.set_cancel_enabled(False)

    def start(self, action: str, filename: str) -> None:
        self.description.set(f"{action}: {filename}")
        self.detail.set("Starting...")
        self.percent.set(0)
        self.tracker.reset()
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
        snapshot = self.tracker.update(done, total)
        self.detail.set(format_transfer_detail(done, total, percent, snapshot))
        bounded = max(0, min(100, percent))
        self.percent.set(max(self.percent.get(), bounded))

    def complete(self, action: str, filename: str, total: int) -> None:
        self.description.set(f"{action} complete: {filename}")
        self.detail.set(f"{total:,} bytes - checksum verified")
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


def format_transfer_detail(
    done: int,
    total: int,
    percent: int,
    snapshot: TransferSnapshot,
) -> str:
    parts = [f"{format_size(done)} / {format_size(total)} ({percent}%)"]
    if snapshot.bytes_per_second > 0:
        parts.append(f"{format_size(round(snapshot.bytes_per_second))}/s")
    if snapshot.eta_seconds is not None:
        parts.append(f"ETA {format_duration(snapshot.eta_seconds)}")
    if snapshot.resumed_from > 0:
        parts.append(f"resumed at {format_size(snapshot.resumed_from)}")
    return " | ".join(parts)


def format_duration(seconds: float) -> str:
    rounded = max(0, math.ceil(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"
