"""Tecla global (push-to-talk) y canal de control para atajos del escritorio.

Linux: evdev (funciona en Wayland y X11; requiere grupo `input`).
Windows: pynput.
Control: socket unix (Linux) o TCP local (Windows) → `nyx toggle`.
"""
from __future__ import annotations

import os
import re
import selectors
import socket
import threading
import time
from pathlib import Path

from .config import IS_WINDOWS, log
from .output import teclado_simulado

CONTROL_PORT = 47321
SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "nyx.sock"


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


_SYMBOLS = {";": "SEMICOLON", ",": "COMMA", ".": "DOT", "/": "SLASH", "'": "APOSTROPHE", "-": "MINUS",
            "=": "EQUAL", "[": "LEFTBRACE", "]": "RIGHTBRACE", "\\": "BACKSLASH", "`": "GRAVE"}
MODIFIERS = {
    "ctrl": ("KEY_LEFTCTRL", "KEY_RIGHTCTRL"), "alt": ("KEY_LEFTALT", "KEY_RIGHTALT"),
    "shift": ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"), "super": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
}


def xkb_options() -> list[str]:
    """Opciones xkb del escritorio (p.ej. ctrl:swapcaps). nyx lee el teclado ANTES de que el
    escritorio aplique estos remapeos, así que necesita saberlos para entender los atajos."""
    import subprocess

    opts: list[str] = []
    env = os.environ.get("XKB_DEFAULT_OPTIONS")  # sway, hyprland, wlroots
    if env:
        opts += env.split(",")
    kde = Path.home() / ".config" / "kxkbrc"
    if kde.is_file():
        for line in kde.read_text(errors="replace").splitlines():
            if line.strip().startswith("Options="):
                opts += line.split("=", 1)[1].split(",")
    if not opts:
        try:  # GNOME
            r = subprocess.run(["gsettings", "get", "org.gnome.desktop.input-sources", "xkb-options"],
                               capture_output=True, text=True, timeout=2)
            opts += re.findall(r"'([^']+)'", r.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    return [o.strip() for o in opts if o.strip()]


_SWAPCAPS = {"ctrl:swapcaps", "ctrl:swapcaps_hyper", "ctrl:swapcaps_and_switch_layout"}
_CAPS_IS_CTRL = {"ctrl:nocaps", "caps:ctrl_modifier"}


def ctrl_key_names(opts: list[str], extra: list[str] | None = None) -> set[str]:
    """Teclas físicas (nombres evdev) que el escritorio trata como Ctrl."""
    keys = {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"}
    if _SWAPCAPS & set(opts):
        keys = (keys - {"KEY_LEFTCTRL"}) | {"KEY_CAPSLOCK"}
    elif _CAPS_IS_CTRL & set(opts):
        keys.add("KEY_CAPSLOCK")
    return keys | set(extra or [])


def parse_combo(spec: str) -> tuple[list[str], str]:
    """"ctrl+;" / "ctrl+KEY_SEMICOLON" → (["ctrl"], "KEY_SEMICOLON")."""
    parts = [p.strip() for p in spec.split("+") if p.strip()] if spec.strip() != "+" else ["+"]
    key = parts[-1]
    key = _SYMBOLS.get(key, key).upper()
    key = key if key.startswith("KEY_") else "KEY_" + key
    mods = [m.lower() for m in parts[:-1]]
    for m in mods:
        if m not in MODIFIERS:
            raise ValueError(f"modificador desconocido '{m}' en '{spec}' (usa ctrl, alt, shift, super)")
    return mods, key


_KEY_DEBUG = bool(os.environ.get("NYX_KEY_DEBUG"))
_CTRL = {29, 97}  # KEY_LEFTCTRL, KEY_RIGHTCTRL
# Modificadores (para depurar atajos sin registrar lo que se escribe):
# ctrl, shift, alt, super, bloq mayús, menú
_MODS = {29, 97, 42, 54, 56, 100, 125, 126, 58, 127, 464}


# ------------------------------------------------------------------- Linux
class EvdevListener(threading.Thread):
    def __init__(self, key: str, ptt: PushToTalk, combos: list | None = None, ctrl_keys: list[str] | None = None):
        super().__init__(daemon=True)
        from evdev import ecodes

        self.e = ecodes
        self.code = ecodes.ecodes[key]
        self.ptt = ptt
        self.known: set[str] = set()
        self.down: set[int] = set()
        # [(grupos de modificadores [{códigos}], código, callback)]
        self.combos = []
        opts = xkb_options()
        mod_names = dict(MODIFIERS)
        mod_names["ctrl"] = tuple(sorted(ctrl_key_names(opts, ctrl_keys)))
        for spec, fn in combos or []:
            mods, k = parse_combo(spec)
            groups = [{ecodes.ecodes[c] for c in mod_names[m]} for m in mods]
            self.combos.append((groups, ecodes.ecodes[k], fn))
        if self.combos and mod_names["ctrl"] != MODIFIERS["ctrl"]:
            log(f"[hotkey] opciones del teclado {opts}: Ctrl = {', '.join(mod_names['ctrl'])}")

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
            if teclado_simulado(name):  # ignorar teclas simuladas (las nuestras, ydotool)
                continue
            caps = set(d.capabilities().get(self.e.EV_KEY, []))
            # también los modificadores de los atajos: hay teclados que mandan Ctrl izquierdo
            # desde un dispositivo interno distinto al de las demás teclas
            wanted = {self.code} | {c for _, c, _ in self.combos} | {m for gs, _, _ in self.combos for g in gs for m in g}
            if caps & wanted:
                sel.register(d, selectors.EVENT_READ)
                added.append(d.name)
        return added

    def run(self):
        sel = selectors.DefaultSelector()
        added = self._scan(sel)
        if not added:
            log(f"[hotkey] no puedo leer teclados con {self.e.KEY[self.code]} — "
                "¿estás en el grupo `input`? (usa `nyx doctor`). Queda el control por atajo: `nyx toggle`.")
        else:
            log("[hotkey] escuchando en:", ", ".join(sorted(set(added))))
        last_scan = time.monotonic()
        while True:
            for key, _ in sel.select(timeout=3):
                dev = key.fileobj
                try:
                    for ev in dev.read():
                        if ev.type == self.e.EV_KEY and ev.value != 2:
                            self._key(ev.code, ev.value == 1, dev.name)
                except OSError:  # teclado desconectado
                    sel.unregister(dev)
                    self.known.discard(dev.path)
            if time.monotonic() - last_scan > 3:  # teclados conectados en caliente
                last_scan = time.monotonic()
                new = self._scan(sel)
                if new:
                    log("[hotkey] nuevo teclado:", ", ".join(new))


    def _key(self, code: int, down: bool, device: str = ""):
        (self.down.add if down else self.down.discard)(code)
        if _KEY_DEBUG and code in _MODS:
            name = self.e.KEY.get(code, code)
            log(f"[hotkey-debug] {name[0] if isinstance(name, list) else name} {'pulsado' if down else 'soltado'} "
                f"(código {code}) en «{device}»")
        if _KEY_DEBUG and down and code not in _CTRL and self.down & _CTRL:
            # depuración de atajos: SOLO teclas pulsadas con Ctrl (no registra lo que escribes)
            name = self.e.KEY.get(code, code)
            log(f"[hotkey-debug] Ctrl + {name[0] if isinstance(name, list) else name} (código {code}); "
                f"combos esperan {[(k, [sorted(g) for g in gs]) for gs, k, _ in self.combos]}")
        (self.ptt.target if code == self.code else self.ptt.other)(down)
        if down:
            for groups, k, fn in self.combos:
                if code == k and all(g & self.down for g in groups):
                    threading.Thread(target=fn, daemon=True).start()


# ----------------------------------------------------------------- Windows
PYNPUT_NAMES = {
    "RIGHTCTRL": "ctrl_r", "LEFTCTRL": "ctrl_l", "RIGHTALT": "alt_gr", "LEFTALT": "alt_l",
    "RIGHTSHIFT": "shift_r", "LEFTSHIFT": "shift_l", "RIGHTMETA": "cmd_r", "LEFTMETA": "cmd_l",
    "CAPSLOCK": "caps_lock", "SCROLLLOCK": "scroll_lock", "PAUSE": "pause", "INSERT": "insert",
    "COMPOSE": "menu", "MENU": "menu",
}


# Teclas de símbolo por código virtual de Windows (distribución US)
_VK = {"SEMICOLON": 0xBA, "EQUAL": 0xBB, "COMMA": 0xBC, "MINUS": 0xBD, "DOT": 0xBE, "SLASH": 0xBF,
       "GRAVE": 0xC0, "LEFTBRACE": 0xDB, "BACKSLASH": 0xDC, "RIGHTBRACE": 0xDD, "APOSTROPHE": 0xDE}


class PynputListener:
    def __init__(self, key: str, ptt: PushToTalk, combos: list | None = None):
        from pynput import keyboard

        K = keyboard.Key
        name = key.removeprefix("KEY_").upper()
        attr = PYNPUT_NAMES.get(name, name.lower())
        self.target = getattr(K, attr)
        self.ptt = ptt
        self.held: set = set()
        mod_keys = {"ctrl": {K.ctrl, K.ctrl_l, K.ctrl_r}, "alt": {K.alt, K.alt_l, K.alt_r, K.alt_gr},
                    "shift": {K.shift, K.shift_l, K.shift_r}, "super": {K.cmd, K.cmd_l, K.cmd_r}}
        self.combos = []
        for spec, fn in combos or []:
            mods, k = parse_combo(spec)
            n = k.removeprefix("KEY_")
            if n in _VK:
                match = ("vk", _VK[n])
            elif len(n) == 1:
                match = ("vk", ord(n))
            else:
                match = ("key", getattr(K, PYNPUT_NAMES.get(n, n.lower())))
            self.combos.append(([mod_keys[m] for m in mods], match, fn))
        self.listener = keyboard.Listener(on_press=self._press, on_release=self._release)

    def _matches(self, k, match):
        kind, val = match
        return (getattr(k, "vk", None) == val) if kind == "vk" else k == val

    def _press(self, k):
        self.held.add(k)
        (self.ptt.target if k == self.target else self.ptt.other)(True)
        for groups, match, fn in self.combos:
            if self._matches(k, match) and all(g & self.held for g in groups):
                threading.Thread(target=fn, daemon=True).start()

    def _release(self, k):
        self.held.discard(k)
        if k == self.target:
            self.ptt.target(False)

    def start(self):
        self.listener.start()
        log(f"[hotkey] escuchando {self.target}")


def make_listener(key: str, ptt: PushToTalk, combos: list | None = None, ctrl_keys: list[str] | None = None):
    """combos: [("ctrl+0", callback), …] — atajos extra que disparan una acción.
    ctrl_keys: teclas físicas extra que cuentan como Ctrl (además de lo que diga xkb)."""
    return PynputListener(key, ptt, combos) if IS_WINDOWS else EvdevListener(key, ptt, combos, ctrl_keys)


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


MAX_PAYLOAD = 1 << 20  # 1 MB
# Comandos que se ejecutan ANTES de responder y devuelven su resultado (pueden tardar minutos).
SYNC_COMMANDS = {"transcribe", "status", "record-start", "record-stop", "agent-start", "agent-restart", "gpu"}
WITH_PAYLOAD = {"say", "say-brief", "order", "transcribe", "record-start"}


class ControlServer(threading.Thread):
    """Protocolo: "<comando>\n<datos opcionales>" y el cliente cierra la escritura.

    Comandos sin datos: start | stop | toggle | cancel | read | hush | ping
    Con datos: say (el texto a leer)
    """

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
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn:
            conn.settimeout(5)
            buf = b""
            try:
                while len(buf) < MAX_PAYLOAD:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            except OSError:
                pass
            cmd, _, payload = buf.decode(errors="replace").partition("\n")
            cmd = cmd.strip()
            fn = self.handlers.get(cmd)
            if fn and cmd in SYNC_COMMANDS:
                conn.settimeout(None)
                try:
                    reply = str(fn(payload))
                except Exception as e:  # noqa: BLE001
                    reply = f"error: {e}"
                try:
                    conn.sendall(reply.encode())
                except OSError:
                    pass
                return
            try:
                conn.sendall(b"ok\n" if fn else b"unknown\n")
            except OSError:
                pass
        if fn:
            fn(payload) if cmd in WITH_PAYLOAD else fn()


def send_command(cmd: str, payload: str = "", timeout: float | None = 5) -> str:
    if IS_WINDOWS:
        s = socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=2)
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(str(SOCKET_PATH))
    with s:
        s.sendall(f"{cmd}\n{payload}".encode())
        s.shutdown(socket.SHUT_WR)
        s.settimeout(timeout)
        chunks = []
        while True:
            c = s.recv(65536)
            if not c:
                break
            chunks.append(c)
        return b"".join(chunks).decode(errors="replace").strip()


def is_running() -> bool:
    try:
        send_command("ping")
        return True
    except OSError:
        return False
