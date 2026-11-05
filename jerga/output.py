"""Escribir el texto donde está el cursor: portapapeles + atajo de pegar.

Linux: wl-clipboard (Wayland) o xclip/xsel (X11) para el portapapeles;
       teclado virtual vía /dev/uinput (python-evdev), con ydotool/xdotool/wtype de reserva.
Windows: pyperclip + pynput.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

from .config import IS_WINDOWS, log
from .platform_env import clean_child_env

UINPUT_NAME = "jerga-virtual-keyboard"


def _parse_combo(combo: str) -> list[str]:
    return [k.strip().lower() for k in combo.split("+") if k.strip()]


# ------------------------------------------------------------- portapapeles
class Clipboard:
    """Interfaz: get(primary) -> bytes|None, set(data, primary)."""

    has_primary = False

    def get(self, primary=False):
        return None

    def set(self, data: bytes, primary=False):
        raise NotImplementedError


class WaylandClipboard(Clipboard):
    has_primary = True

    def __init__(self):
        self.env = clean_child_env()

    def get(self, primary=False):
        try:
            r = subprocess.run(["wl-paste", "--no-newline"] + (["--primary"] if primary else []),
                               capture_output=True, timeout=1, env=self.env)
            return r.stdout if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    def set(self, data, primary=False):
        subprocess.run(["wl-copy"] + (["--primary"] if primary else []),
                       input=data, check=False, env=self.env)


class XClipboard(Clipboard):
    has_primary = True

    def __init__(self):
        self.env = clean_child_env()
        self.tool = "xclip" if shutil.which("xclip") else "xsel"

    def _args(self, primary, write):
        if self.tool == "xclip":
            return ["xclip", "-selection", "primary" if primary else "clipboard"] + ([] if write else ["-o"])
        return ["xsel", "--primary" if primary else "--clipboard"] + (["--input"] if write else ["--output"])

    def get(self, primary=False):
        try:
            r = subprocess.run(self._args(primary, False), capture_output=True, timeout=1, env=self.env)
            return r.stdout if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    def set(self, data, primary=False):
        subprocess.run(self._args(primary, True), input=data, check=False, env=self.env)


class WindowsClipboard(Clipboard):
    def __init__(self):
        import pyperclip

        self.pc = pyperclip

    def get(self, primary=False):
        try:
            return self.pc.paste().encode()
        except Exception:  # noqa: BLE001
            return None

    def set(self, data, primary=False):
        self.pc.copy(data.decode())


# ----------------------------------------------------------------- teclado
class UInputKeys:
    """Teclado virtual del kernel: funciona en Wayland y X11 sin daemons."""

    def __init__(self):
        from evdev import UInput, ecodes

        self.e = ecodes
        self.ui = UInput({ecodes.EV_KEY: [c for c in ecodes.keys if 0 < c < 256]}, name=UINPUT_NAME)
        time.sleep(0.3)  # dar tiempo al compositor a registrar el dispositivo

    def code(self, k: str) -> int:
        alias = {"ctrl": "LEFTCTRL", "shift": "LEFTSHIFT", "alt": "LEFTALT", "super": "LEFTMETA",
                 "meta": "LEFTMETA", "ins": "INSERT"}
        return self.e.ecodes["KEY_" + alias.get(k, k).upper()]

    def combo(self, combo: str):
        codes = [self.code(k) for k in _parse_combo(combo)]
        for c in codes:
            self.ui.write(self.e.EV_KEY, c, 1)
            self.ui.syn()
            time.sleep(0.01)
        for c in reversed(codes):
            self.ui.write(self.e.EV_KEY, c, 0)
            self.ui.syn()
            time.sleep(0.01)

    def type(self, text: str):
        raise NotImplementedError("usa method = 'paste' (uinput no sabe tu distribución de teclado)")


class YdotoolKeys:
    CODES = {"shift": 42, "ctrl": 29, "alt": 56, "super": 125, "insert": 110, "v": 47, "enter": 28}

    def __init__(self):
        self.env = clean_child_env()
        self.env.setdefault("YDOTOOL_SOCKET", f"/run/user/{os.getuid()}/.ydotool_socket")

    def combo(self, combo):
        codes = [self.CODES[k] for k in _parse_combo(combo)]
        seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
        subprocess.run(["ydotool", "key", *seq], env=self.env, check=False)

    def type(self, text):
        subprocess.run(["ydotool", "type", "--", text], env=self.env, check=False)


class XdotoolKeys:
    def __init__(self):
        self.env = clean_child_env()

    def combo(self, combo):
        names = {"insert": "Insert", "ctrl": "ctrl", "shift": "shift", "alt": "alt", "super": "super"}
        subprocess.run(["xdotool", "key", "--clearmodifiers",
                        "+".join(names.get(k, k) for k in _parse_combo(combo))], env=self.env, check=False)

    def type(self, text):
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text], env=self.env, check=False)


class WtypeKeys:  # compositores wlroots (Sway, Hyprland…)
    def __init__(self):
        self.env = clean_child_env()

    def combo(self, combo):
        keys = _parse_combo(combo)
        mods, key = keys[:-1], keys[-1]
        names = {"insert": "Insert", "v": "v"}
        args = ["wtype"]
        for m in mods:
            args += ["-M", m]
        args += ["-k", names.get(key, key)]
        for m in reversed(mods):
            args += ["-m", m]
        subprocess.run(args, env=self.env, check=False)

    def type(self, text):
        subprocess.run(["wtype", "--", text], env=self.env, check=False)


class PynputKeys:
    def __init__(self):
        from pynput.keyboard import Controller, Key

        self.kb, self.Key = Controller(), Key

    def _k(self, name):
        alias = {"ctrl": "ctrl", "shift": "shift", "alt": "alt", "super": "cmd", "insert": "insert"}
        n = alias.get(name, name)
        return getattr(self.Key, n) if len(n) > 1 else n

    def combo(self, combo):
        keys = [self._k(k) for k in _parse_combo(combo)]
        for k in keys:
            self.kb.press(k)
        for k in reversed(keys):
            self.kb.release(k)

    def type(self, text):
        self.kb.type(text)


def pick_clipboard() -> Clipboard | None:
    if IS_WINDOWS:
        return WindowsClipboard()
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return WaylandClipboard()
    if os.environ.get("DISPLAY") and (shutil.which("xclip") or shutil.which("xsel")):
        return XClipboard()
    return None


def pick_keys():
    if IS_WINDOWS:
        return PynputKeys()
    errors = []
    try:
        return UInputKeys()
    except Exception as e:  # noqa: BLE001
        errors.append(f"uinput: {e}")
    if shutil.which("ydotool"):
        return YdotoolKeys()
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wtype"):
        return WtypeKeys()
    if os.environ.get("DISPLAY") and shutil.which("xdotool"):
        return XdotoolKeys()
    log("[output] sin forma de simular teclas:", "; ".join(errors))
    return None


# ------------------------------------------------------------------ salida
class Output:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.clip = pick_clipboard()
        self.keys = pick_keys() if cfg["method"] != "clipboard" else None
        log(f"[output] portapapeles={type(self.clip).__name__ if self.clip else '—'} "
            f"teclas={type(self.keys).__name__ if self.keys else '—'}")

    def finalize(self, text: str) -> str:
        if self.cfg["strip_final_period"] and text.endswith(".") and not text.endswith(".."):
            text = text[:-1]
        if self.cfg["trailing_space"] and text:
            text += " "
        return text

    def emit(self, text: str):
        if not text:
            return
        method = self.cfg["method"]
        if method == "type" and self.keys:
            self.keys.type(text)
            return
        if self.clip is None:
            raise RuntimeError("no hay herramienta de portapapeles (instala wl-clipboard o xclip)")
        restore = method == "paste" and self.cfg["restore_clipboard"]
        old = self.clip.get() if restore else None
        old_p = self.clip.get(primary=True) if restore and self.clip.has_primary else None
        data = text.encode()
        # Clipboard + primary: así shift+insert funciona tanto en apps como en terminales.
        self.clip.set(data)
        if self.clip.has_primary:
            self.clip.set(data, primary=True)
        if method == "clipboard" or self.keys is None:
            return
        time.sleep(0.05)
        self.keys.combo(self.cfg["paste_keys"])
        if restore:
            def later():
                time.sleep(0.6)
                if old:
                    self.clip.set(old)
                if old_p:
                    self.clip.set(old_p, primary=True)

            threading.Thread(target=later, daemon=True).start()
