"""Tecla global (push-to-talk) y canal de control para atajos del escritorio.

Linux: evdev (funciona en Wayland y X11; requiere grupo `input`).
Windows: pynput.
Control: socket unix (Linux) o TCP local (Windows) → `jerga toggle`.
"""
from __future__ import annotations

import os
import selectors
import socket
import threading
import time
from pathlib import Path

from .config import IS_WINDOWS, log

CONTROL_PORT = 47321
SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "jerga.sock"


class PushToTalk:
    """Máquina de estados común: hold (mantener) o toggle."""

    def __init__(self, mode, on_start, on_stop, on_cancel):
        self.mode = mode
        self.on_start, self.on_stop, self.on_cancel = on_start, on_stop, on_cancel
        self.held = self.recording = self.dirty = False

    def target(self, down: bool):
        if self.mode == "hold":
            if down and not self.held:
                self.held, self.dirty, self.recording = True, False, True
                self.on_start()
            elif not down and self.held:
                self.held = False
                if self.recording and not self.dirty:
                    self.on_stop()
                self.recording = False
        elif down:
            self.recording = not self.recording
            (self.on_start if self.recording else self.on_stop)()

    def other(self, down: bool):
        # Ctrl+C, Ctrl+V… mientras mantienes la tecla: era un atajo, no dictado.
        if down and self.held and self.mode == "hold":
            self.dirty = True
            if self.recording:
                self.recording = False
                self.on_cancel()


# ------------------------------------------------------------------- Linux
class EvdevListener(threading.Thread):
    def __init__(self, key: str, ptt: PushToTalk):
        super().__init__(daemon=True)
        from evdev import ecodes

        self.e = ecodes
        self.code = ecodes.ecodes[key]
        self.ptt = ptt
        self.known: set[str] = set()

    def _scan(self, sel):
        import evdev

        added = []
        for path in evdev.list_devices():
            if path in self.known:
                continue
            try:
                d = evdev.InputDevice(path)
            except OSError:
                continue
            self.known.add(path)
            name = d.name.lower()
            if "ydotool" in name or "jerga" in name:  # ignorar teclas simuladas
                continue
            if self.code in d.capabilities().get(self.e.EV_KEY, []):
                sel.register(d, selectors.EVENT_READ)
                added.append(d.name)
        return added

    def run(self):
        sel = selectors.DefaultSelector()
        added = self._scan(sel)
        if not added:
            log(f"[hotkey] no puedo leer teclados con {self.e.KEY[self.code]} — "
                "¿estás en el grupo `input`? (usa `jerga doctor`). Queda el control por atajo: `jerga toggle`.")
        else:
            log("[hotkey] escuchando en:", ", ".join(sorted(set(added))))
        last_scan = time.monotonic()
        while True:
            for key, _ in sel.select(timeout=3):
                dev = key.fileobj
                try:
                    for ev in dev.read():
                        if ev.type == self.e.EV_KEY and ev.value != 2:
                            (self.ptt.target if ev.code == self.code else self.ptt.other)(ev.value == 1)
                except OSError:  # teclado desconectado
                    sel.unregister(dev)
                    self.known.discard(dev.path)
            if time.monotonic() - last_scan > 3:  # teclados conectados en caliente
                last_scan = time.monotonic()
                new = self._scan(sel)
                if new:
                    log("[hotkey] nuevo teclado:", ", ".join(new))


# ----------------------------------------------------------------- Windows
PYNPUT_NAMES = {
    "RIGHTCTRL": "ctrl_r", "LEFTCTRL": "ctrl_l", "RIGHTALT": "alt_gr", "LEFTALT": "alt_l",
    "RIGHTSHIFT": "shift_r", "LEFTSHIFT": "shift_l", "RIGHTMETA": "cmd_r", "LEFTMETA": "cmd_l",
    "CAPSLOCK": "caps_lock", "SCROLLLOCK": "scroll_lock", "PAUSE": "pause", "INSERT": "insert",
    "COMPOSE": "menu", "MENU": "menu",
}


class PynputListener:
    def __init__(self, key: str, ptt: PushToTalk):
        from pynput import keyboard

        name = key.removeprefix("KEY_").upper()
        attr = PYNPUT_NAMES.get(name, name.lower())
        self.target = getattr(keyboard.Key, attr)
        self.ptt = ptt
        self.listener = keyboard.Listener(on_press=self._press, on_release=self._release)

    def _press(self, k):
        (self.ptt.target if k == self.target else self.ptt.other)(True)

    def _release(self, k):
        if k == self.target:
            self.ptt.target(False)

    def start(self):
        self.listener.start()
        log(f"[hotkey] escuchando {self.target}")


def make_listener(key: str, ptt: PushToTalk):
    return PynputListener(key, ptt) if IS_WINDOWS else EvdevListener(key, ptt)


# ----------------------------------------------------------------- control
def _server_socket() -> socket.socket:
    if IS_WINDOWS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", CONTROL_PORT))
    else:
        SOCKET_PATH.unlink(missing_ok=True)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(SOCKET_PATH))
    s.listen()
    return s


class ControlServer(threading.Thread):
    """Comandos: start | stop | toggle | cancel."""

    def __init__(self, handlers: dict):
        super().__init__(daemon=True)
        self.handlers = handlers

    def run(self):
        try:
            srv = _server_socket()
        except OSError as e:
            log(f"[control] no se pudo abrir el canal de control: {e}")
            return
        while True:
            conn, _ = srv.accept()
            with conn:
                cmd = conn.recv(64).decode().strip()
                fn = self.handlers.get(cmd)
                conn.sendall(b"ok\n" if fn else b"unknown\n")
                if fn:
                    fn()


def send_command(cmd: str) -> str:
    if IS_WINDOWS:
        s = socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=2)
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(SOCKET_PATH))
    with s:
        s.sendall(cmd.encode())
        return s.recv(64).decode().strip()


def is_running() -> bool:
    try:
        send_command("ping")
        return True
    except OSError:
        return False
