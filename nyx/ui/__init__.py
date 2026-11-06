"""Widget: píldora flotante. Backends:

- gtk:  GTK4 + layer-shell → Wayland con KDE, Sway, Hyprland… (no roba el foco)
- tk:   Tkinter → Windows, X11 y GNOME (vía XWayland)
- none: sin ventana, solo log
"""
from __future__ import annotations

import os
import sys

from ..config import log


def _gtk_ok() -> bool:
    if not os.environ.get("WAYLAND_DISPLAY"):
        return False
    if "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower():
        return False  # mutter no implementa layer-shell
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _tk_ok() -> bool:
    try:
        import tkinter  # noqa: F401

        return sys.platform == "win32" or bool(os.environ.get("DISPLAY"))
    except Exception:  # noqa: BLE001
        return False


def available() -> list[str]:
    out = []
    if _gtk_ok():
        out.append("gtk")
    if _tk_ok():
        out.append("tk")
    return out + ["none"]


def create(backend: str = "auto"):
    avail = available()
    if backend == "auto":
        backend = avail[0]
    elif backend not in avail:
        log(f"[ui] backend '{backend}' no disponible aquí; disponibles: {avail}")
        backend = avail[0]
    log(f"[ui] widget: {backend}")
    if backend == "gtk":
        from .gtk_layer import GtkPill

        return GtkPill()
    if backend == "tk":
        from .tk_pill import TkPill

        return TkPill()
    from .base import HeadlessUI

    return HeadlessUI()
