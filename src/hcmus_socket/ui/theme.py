"""Visual theme shared by the desktop UI views."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


COLORS = {
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
}


def configure_modern_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=COLORS["window"])
    style.configure("App.TFrame", background=COLORS["window"])
    style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
    style.configure(
        "Card.TFrame", background=COLORS["card"], relief="solid", borderwidth=1
    )
    style.configure("CardBody.TFrame", background=COLORS["card"])
    style.configure(
        "Title.TLabel",
        background=COLORS["card"],
        foreground=COLORS["text"],
        font=("Segoe UI Semibold", 14),
    )
    style.configure(
        "Subtitle.TLabel",
        background=COLORS["card"],
        foreground=COLORS["muted"],
        font=("Segoe UI", 9),
    )
    style.configure(
        "Field.TLabel",
        background=COLORS["card"],
        foreground=COLORS["text"],
        font=("Segoe UI Semibold", 9),
    )
    style.configure(
        "Status.TLabel",
        background=COLORS["window"],
        foreground=COLORS["muted"],
        font=("Segoe UI", 9),
        padding=(14, 7),
    )
    for name, background, foreground in (
        ("Success.TLabel", "#EAF8EF", COLORS["success"]),
        ("Offline.TLabel", "#F1F4F8", COLORS["muted"]),
    ):
        style.configure(
            name,
            background=background,
            foreground=foreground,
            font=("Segoe UI Semibold", 9),
            padding=(12, 6),
        )
    style.configure("Modern.TEntry", padding=(10, 9), fieldbackground="#FFFFFF")
    style.configure(
        "Accent.TButton",
        background=COLORS["accent"],
        foreground="#FFFFFF",
        borderwidth=0,
        padding=(18, 10),
        font=("Segoe UI Semibold", 10),
    )
    style.map(
        "Accent.TButton",
        background=[("active", COLORS["accent_hover"]), ("disabled", "#B9D8D5")],
        foreground=[("disabled", "#F5F8F8")],
    )
    style.configure(
        "Outline.TButton",
        background="#FFFFFF",
        foreground=COLORS["cyan"],
        bordercolor=COLORS["border"],
        padding=(14, 8),
        font=("Segoe UI Semibold", 9),
    )
    style.map("Outline.TButton", background=[("active", "#EFF8FC")])
    style.configure(
        "Danger.TButton",
        background="#FFFFFF",
        foreground=COLORS["danger"],
        bordercolor="#F5A4AA",
        padding=(14, 8),
        font=("Segoe UI Semibold", 9),
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#FFF1F2"), ("disabled", "#F5F6F8")],
        foreground=[("disabled", COLORS["disabled"])],
    )
    for name, background, foreground in (
        ("Nav.TButton", COLORS["sidebar"], COLORS["text"]),
        ("ActiveNav.TButton", COLORS["accent"], "#FFFFFF"),
    ):
        style.configure(
            name,
            background=background,
            foreground=foreground,
            borderwidth=0,
            anchor="w",
            padding=(18, 12),
            font=("Segoe UI Semibold", 10),
        )
    style.map("Nav.TButton", background=[("active", "#DDF2F6")])
    style.map(
        "ActiveNav.TButton", background=[("active", COLORS["accent_hover"])]
    )
    style.configure(
        "Modern.Treeview",
        background="#FFFFFF",
        fieldbackground="#FFFFFF",
        foreground=COLORS["text"],
        rowheight=34,
        borderwidth=0,
        font=("Segoe UI", 10),
    )
    style.configure(
        "Modern.Treeview.Heading",
        background="#F8FBFE",
        foreground=COLORS["text"],
        relief="flat",
        padding=(8, 9),
        font=("Segoe UI Semibold", 9),
    )
    style.map("Modern.Treeview", background=[("selected", "#DDF5F4")])
    style.configure(
        "Modern.Horizontal.TProgressbar",
        troughcolor=COLORS["track"],
        background=COLORS["accent"],
        borderwidth=0,
        thickness=9,
    )
