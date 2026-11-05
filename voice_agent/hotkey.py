"""Tecla global vía evdev (funciona en Wayland; requiere grupo `input`)
y socket de control para atajos de KDE (`voice-agent toggle`)."""
from __future__ import annotations

import os
import selectors
import socket
import threading
from pathlib import Path

import evdev
from evdev import ecodes

SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "voice-agent.sock"


class HotkeyListener(threading.Thread):
    """Llama a on_start / on_stop / on_cancel según el modo (hold|toggle)."""

    def __init__(self, key: str, mode: str, on_start, on_stop, on_cancel):
        super().__init__(daemon=True)
        self.code = ecodes.ecodes[key]
        self.mode = mode
        self.on_start, self.on_stop, self.on_cancel = on_start, on_stop, on_cancel
        self.held = False
        self.recording = False
        self.dirty = False  # se pulsó otra tecla mientras estaba mantenida

    def _devices(self):
        devs = []
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
            except OSError:
                continue
            if "ydotool" in d.name.lower():  # ignorar nuestras propias pulsaciones
                continue
            keys = d.capabilities().get(ecodes.EV_KEY, [])
            if self.code in keys:
                devs.append(d)
        return devs

    def run(self):
        sel = selectors.DefaultSelector()
        devs = self._devices()
        if not devs:
            print(f"[hotkey] ningún dispositivo tiene la tecla {ecodes.KEY[self.code]}")
            return
        for d in devs:
            sel.register(d, selectors.EVENT_READ)
        print("[hotkey] escuchando en:", ", ".join(sorted({d.name for d in devs})))
        while True:
            for key, _ in sel.select():
                dev = key.fileobj
                try:
                    events = list(dev.read())
                except OSError:  # dispositivo desconectado
                    sel.unregister(dev)
                    continue
                for ev in events:
                    if ev.type == ecodes.EV_KEY:
                        self._handle(ev.code, ev.value)

    def _handle(self, code: int, value: int):
        if value == 2:  # autorepeat
            return
        if code != self.code:
            if value == 1 and self.held and self.mode == "hold":
                # Ctrl+C, Ctrl+V... no era dictado → cancelar
                self.dirty = True
                if self.recording:
                    self.recording = False
                    self.on_cancel()
            return
        if self.mode == "hold":
            if value == 1:
                self.held, self.dirty = True, False
                self.recording = True
                self.on_start()
            elif value == 0:
                self.held = False
                if self.recording and not self.dirty:
                    self.on_stop()
                self.recording = False
        else:  # toggle
            if value == 1:
                self.recording = not self.recording
                (self.on_start if self.recording else self.on_stop)()


class ControlSocket(threading.Thread):
    """Comandos de texto por socket unix: start | stop | toggle | cancel."""

    def __init__(self, handlers: dict):
        super().__init__(daemon=True)
        self.handlers = handlers

    def run(self):
        SOCKET_PATH.unlink(missing_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(SOCKET_PATH))
        srv.listen()
        while True:
            conn, _ = srv.accept()
            with conn:
                cmd = conn.recv(64).decode().strip()
                fn = self.handlers.get(cmd)
                conn.sendall(b"ok\n" if fn else b"unknown\n")
                if fn:
                    fn()


def send_command(cmd: str) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(SOCKET_PATH))
    s.sendall(cmd.encode())
    return s.recv(64).decode().strip()
