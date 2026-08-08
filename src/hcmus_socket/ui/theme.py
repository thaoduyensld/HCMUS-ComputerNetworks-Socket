"""Runtime-selectable visual themes shared by the desktop UI views."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "window": "#F5F9FD",
        "sidebar": "#ECF8FB",
        "card": "#FFFFFF",
        "border": "#DDE8F2",
        "text": "#112344",
        "muted": "#61708C",
        "accent": "#079C91",
        "accent_hover": "#087F79",
        "cyan": "#089FC1",
        "success": "#159447",
        "danger": "#EF4B55",
        "disabled": "#A5AFC2",
        "track": "#E7EDF4",
        "input": "#FFFFFF",
        "soft": "#EFF8FC",
        "selection": "#DDF5F4",
        "heading": "#F8FBFE",
    },
    "dark": {
        "window": "#0E1726",
        "sidebar": "#101F31",
        "card": "#17263A",
        "border": "#2A3D55",
        "text": "#EAF2FF",
        "muted": "#9EB0C8",
        "accent": "#16B8AA",
        "accent_hover": "#0E958B",
        "cyan": "#42C7E8",
        "success": "#55D68A",
        "danger": "#FF747D",
        "disabled": "#66758A",
        "track": "#2A3A50",
        "input": "#101C2C",
        "soft": "#20344A",
        "selection": "#245A59",
        "heading": "#1C2D43",
    },
}

COLORS = PALETTES["light"]


def palette_for(mode: str) -> dict[str, str]:
    """Return the immutable-by-convention palette for a supported mode."""

    try:
        return PALETTES[mode]
    except KeyError as error:
        raise ValueError("theme mode must be 'light' or 'dark'") from error


def configure_modern_theme(root: tk.Tk, mode: str = "light") -> dict[str, str]:
    """Apply *mode* to all named styles and return its palette."""

    colors = palette_for(mode)
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=colors["window"])
    style.configure("App.TFrame", background=colors["window"])
    style.configure("Sidebar.TFrame", background=colors["sidebar"])
    style.configure(
        "Card.TFrame", background=colors["card"], relief="solid", borderwidth=1
    )
    style.configure("CardBody.TFrame", background=colors["card"])
    for name, background, foreground, font in (
        ("Title.TLabel", colors["card"], colors["text"], ("Segoe UI Semibold", 14)),
        ("Subtitle.TLabel", colors["card"], colors["muted"], ("Segoe UI", 9)),
        ("Field.TLabel", colors["card"], colors["text"], ("Segoe UI Semibold", 9)),
        ("TransferTitle.TLabel", colors["card"], colors["text"], ("Segoe UI Semibold", 10)),
        ("Summary.TLabel", colors["card"], colors["success"], ("Segoe UI Semibold", 9)),
        ("SidebarBrand.TLabel", colors["sidebar"], colors["text"], ("Segoe UI Semibold", 18)),
        ("SidebarIcon.TLabel", colors["sidebar"], colors["accent"], ("Segoe UI Symbol", 34)),
        ("SidebarMuted.TLabel", colors["sidebar"], colors["muted"], ("Segoe UI", 9)),
    ):
        style.configure(name, background=background, foreground=foreground, font=font)
    style.configure(
        "Status.TLabel",
        background=colors["window"],
        foreground=colors["muted"],
        font=("Segoe UI", 9),
        padding=(14, 7),
    )
    style.configure(
        "Success.TLabel",
        background=colors["selection"],
        foreground=colors["success"],
        font=("Segoe UI Semibold", 9),
        padding=(12, 6),
    )
    style.configure(
        "Offline.TLabel",
        background=colors["soft"],
        foreground=colors["muted"],
        font=("Segoe UI Semibold", 9),
        padding=(12, 6),
    )
    style.configure(
        "Modern.TEntry",
        padding=(10, 9),
        fieldbackground=colors["input"],
        foreground=colors["text"],
        insertcolor=colors["text"],
    )
    style.configure(
        "TRadiobutton",
        background=colors["card"],
        foreground=colors["text"],
        font=("Segoe UI", 10),
    )
    style.map(
        "TRadiobutton",
        background=[("active", colors["card"])],
        foreground=[("disabled", colors["disabled"])],
    )
    style.configure(
        "Accent.TButton",
        background=colors["accent"],
        foreground="#FFFFFF",
        borderwidth=0,
        padding=(18, 10),
        font=("Segoe UI Semibold", 10),
    )
    style.map(
        "Accent.TButton",
        background=[("active", colors["accent_hover"]), ("disabled", colors["border"])],
        foreground=[("disabled", colors["disabled"])],
    )
    for name, foreground in (
        ("Outline.TButton", colors["cyan"]),
        ("Danger.TButton", colors["danger"]),
    ):
        style.configure(
            name,
            background=colors["card"],
            foreground=foreground,
            bordercolor=colors["border"],
            padding=(14, 8),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            name,
            background=[("active", colors["soft"]), ("disabled", colors["card"])],
            foreground=[("disabled", colors["disabled"])],
        )
    for name, background, foreground in (
        ("Nav.TButton", colors["sidebar"], colors["text"]),
        ("ActiveNav.TButton", colors["accent"], "#FFFFFF"),
        ("FileCard.TButton", colors["soft"], colors["text"]),
        ("ActiveFileCard.TButton", colors["selection"], colors["accent"]),
    ):
        style.configure(
            name,
            background=background,
            foreground=foreground,
            borderwidth=0,
            anchor="w" if "Nav" in name else "center",
            padding=(18, 12),
            font=("Segoe UI Semibold", 10),
        )
    style.map("Nav.TButton", background=[("active", colors["soft"])])
    style.map("FileCard.TButton", background=[("active", colors["selection"])])
    style.configure(
        "Modern.Treeview",
        background=colors["card"],
        fieldbackground=colors["card"],
        foreground=colors["text"],
        rowheight=34,
        borderwidth=0,
        font=("Segoe UI", 10),
    )
    style.configure(
        "Modern.Treeview.Heading",
        background=colors["heading"],
        foreground=colors["text"],
        relief="flat",
        padding=(8, 9),
        font=("Segoe UI Semibold", 9),
    )
    style.map("Modern.Treeview", background=[("selected", colors["selection"])])
    style.configure(
        "Modern.Horizontal.TProgressbar",
        troughcolor=colors["track"],
        background=colors["accent"],
        borderwidth=0,
        thickness=9,
    )
    return colors
