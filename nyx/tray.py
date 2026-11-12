"""Icono en la bandeja del sistema (`nyx tray`).

Proceso aparte del servicio: el widget usa GTK4 y AppIndicator usa GTK3, que no pueden
convivir en el mismo proceso. Habla con el servicio por el canal de control (status,
toggle, read, hush, transcribe…) y se cierra solo si el servicio desaparece.

Color del icono: gris = listo · rojo = grabando · azul = transcribiendo/cargando ·
morado = leyendo · ámbar apagado = GPU libre (modelos descargados) · naranja = sin servicio.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time

from . import config
from .hotkey import send_command

COLORS = {
    "idle": (142, 142, 147),
    "recording": (255, 69, 58),
    "busy": (10, 132, 255),
    "speaking": (191, 90, 242),
    "free": (200, 130, 50),
    "down": (255, 159, 10),
}
LABELS = {
    "idle": "lista",
    "recording": "grabando…",
    "busy": "trabajando…",
    "speaking": "leyendo en voz alta",
    "free": "GPU libre",
    "down": "sin servicio",
}
GIVE_UP_AFTER = 8.0  # s sin servicio → el tray se cierra (el servicio nuevo arranca otro)


def icon_image(state: str, size: int = 64):
    """Micrófono dibujado con Pillow sobre un círculo del color del estado."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, size - 2, size - 2), fill=COLORS[state] + (255,))
    w = size
    white = (255, 255, 255, 255)
    # cápsula del micro
    d.rounded_rectangle((w * 0.38, w * 0.18, w * 0.62, w * 0.56), radius=int(w * 0.12), fill=white)
    # soporte en U
    d.arc((w * 0.28, w * 0.30, w * 0.72, w * 0.68), start=0, end=180, fill=white, width=max(2, w // 16))
    d.line((w * 0.5, w * 0.68, w * 0.5, w * 0.80), fill=white, width=max(2, w // 16))
    d.line((w * 0.38, w * 0.80, w * 0.62, w * 0.80), fill=white, width=max(2, w // 16))
    return img


def stamp_s(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def state_of(st: dict | None) -> str:
    if st is None:
        return "down"
    if st.get("recording") or st.get("session"):
        return "recording"
    if st.get("speaking"):
        return "speaking"
    if st.get("gpu_free"):  # antes que "modelo no listo": si no, free se pintaría azul busy
        return "free"
    if st.get("busy") or not st.get("stt_ready"):
        return "busy"
    return "idle"


def fetch_status() -> dict | None:
    try:
        return json.loads(send_command("status", timeout=3))
    except (OSError, ValueError):
        return None


def session_item_visible(status: dict | None) -> bool:
    """«Sesión nueva» (rotación a mano del backend efímero) solo cuando aplica: el status
    ya expone nyx.backend (spec 008, D7)."""
    return ((status or {}).get("nyx") or {}).get("backend") == "efimero"


def notify(title: str, body: str = "") -> None:
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "nyx", "-i", "audio-input-microphone", title, body])


def pick_files() -> list[str]:
    """Selector de ficheros nativo (kdialog/zenity en Linux, Tk en Windows)."""
    filt = "*.mp3 *.wav *.ogg *.opus *.oga *.m4a *.aac *.flac *.mp4 *.mkv *.webm *.mov"
    start = os.path.expanduser("~/Descargas") if os.path.isdir(os.path.expanduser("~/Descargas")) else os.path.expanduser("~")
    if shutil.which("kdialog"):
        r = subprocess.run(["kdialog", "--title", "Transcribir con nyx", "--multiple", "--separate-output",
                            "--getopenfilename", start, f"Audio y vídeo ({filt})"], capture_output=True, text=True)
        return [line for line in r.stdout.splitlines() if line.strip()]
    if shutil.which("zenity"):
        r = subprocess.run(["zenity", "--file-selection", "--multiple", "--separator=\n", "--title=Transcribir con nyx",
                            f"--filename={start}/", f"--file-filter=Audio y vídeo | {filt}"], capture_output=True, text=True)
        return [line for line in r.stdout.splitlines() if line.strip()]
    from tkinter import Tk, filedialog

    root = Tk()
    root.withdraw()
    files = list(filedialog.askopenfilenames(title="Transcribir con nyx", initialdir=start))
    root.destroy()
    return files


def open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path])


def nyx_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "nyx", *args]


def main() -> int:
    if sys.platform.startswith("linux"):
        os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")
    try:
        import pystray
    except ImportError:
        print("nyx tray: falta pystray (pip install pystray)", file=sys.stderr)
        return 1
    from pystray import Menu
    from pystray import MenuItem as Item

    current = {"state": "down", "status": None}

    def send(cmd: str, report: bool = False) -> None:
        try:
            r = send_command(cmd)
            if report and r and r != "ok":
                notify("nyx", r)  # p. ej. "espera a que termine": el servicio rechazó (spec A5)
        except OSError:
            notify("nyx no está en marcha")

    def transcribe(_icon=None, _item=None):
        def work():
            files = pick_files()
            if not files:
                return
            notify("Transcribiendo…", "\n".join(os.path.basename(f) for f in files))
            r = subprocess.run(nyx_cmd("transcribe", *files), capture_output=True, text=True)
            lines = [line for line in r.stderr.splitlines() if line.startswith(("✔", "✘"))]
            notify("Transcripción terminada" if r.returncode == 0 else "Transcripción con errores", "\n".join(lines)[:400])
            done = [line.split("→ ", 1)[1].split("  [")[0] for line in lines if line.startswith("✔") and "→ " in line]
            if len(done) == 1:
                open_path(done[0])

        threading.Thread(target=work, daemon=True).start()

    def agent_restart(_icon=None, _item=None):
        def work():
            r = subprocess.run(nyx_cmd("agent", "restart"), capture_output=True, text=True)
            notify("Nyx", (r.stdout or r.stderr).strip()[:300])
        threading.Thread(target=work, daemon=True).start()

    def nyx_label(_item=None) -> str:
        t = (current["status"] or {}).get("nyx") or {}
        if not t:
            return "Nyx"
        if t.get("backend") is None:
            return "Nyx · no disponible"
        state = {"idle": "lista", "working": "trabajando", "blocked": "esperando tu aprobación",
                 "done": "lista", None: "arrancando…"}.get(t.get("state"), t.get("state"))
        where = "herdr" if t["backend"] == "herdr" else "segundo plano"
        return f"Nyx · {state} ({where})"

    def nyx_in_herdr(_item=None) -> bool:
        return ((current["status"] or {}).get("nyx") or {}).get("backend") == "herdr"

    def nyx_focus(_icon=None, _item=None):
        if shutil.which("herdr"):
            subprocess.Popen(["herdr", "agent", "focus", "nyx"])

    def restart(_icon=None, _item=None):
        if shutil.which("systemctl"):
            subprocess.Popen(["systemctl", "--user", "restart", "nyx"])
            notify("Reiniciando nyx…")

    def title_text(_item=None) -> str:
        st = current["status"]
        if st and st.get("session"):
            return f"nyx · grabando sesión ({st['session']['kind']}) {stamp_s(st['session']['elapsed'])}"
        base = f"nyx · {LABELS[current['state']]}"
        if st and st.get("stt_device"):
            base += f" ({st['stt_device']})"
        return base

    def speak_label(_item=None) -> str:
        st = current["status"] or {}
        return "Callar" if st.get("speaking") else f"Leer selección ({st.get('read_key', 'ctrl+;')})"

    def dictate_label(_item=None) -> str:
        st = current["status"] or {}
        if st.get("recording"):
            return "Terminar dictado"
        key = st.get("dictation_key", "").removeprefix("KEY_").replace("RIGHTCTRL", "Ctrl derecho")
        return f"Dictar ({key})" if key else "Dictar"

    def gpu_label(_item=None) -> str:  # spec 006: toggle dinámico según el modo
        st = current["status"] or {}
        return "Usar GPU (carga modelo)" if st.get("gpu_free") else "Liberar GPU"

    def speak_action(_icon=None, _item=None):
        st = current["status"] or {}
        send("hush" if st.get("speaking") else "read")

    up = lambda _item=None: current["state"] != "down"  # noqa: E731
    in_session = lambda _item=None: bool((current["status"] or {}).get("session"))  # noqa: E731
    no_session = lambda _item=None: up() and not in_session()  # noqa: E731

    def record(*flags):
        def go(_icon=None, _item=None):
            r = subprocess.run(nyx_cmd("record", *flags), capture_output=True, text=True)
            if r.returncode != 0:
                notify("No se pudo grabar", (r.stderr or r.stdout).strip()[:300])
        return go

    def record_stop(_icon=None, _item=None):
        def work():
            r = subprocess.run(nyx_cmd("record", "stop"), capture_output=True, text=True)
            path = r.stdout.strip()
            if r.returncode == 0 and path:
                open_path(path)
        threading.Thread(target=work, daemon=True).start()

    menu = Menu(
        Item(title_text, None, enabled=False),
        Menu.SEPARATOR,
        Item(dictate_label, lambda: send("toggle"), enabled=up, default=True),
        Item(speak_label, speak_action, enabled=up),
        Item("Transcribir fichero…", transcribe, enabled=up),
        Item("Grabar sesión", Menu(
            Item("Micrófono", record(), enabled=no_session),
            Item("Audio del PC", record("--system"), enabled=no_session),
            Item("Micrófono + audio del PC", record("--both"), enabled=no_session),
        ), visible=lambda _i=None: not in_session()),
        Item("Parar sesión y abrir", record_stop, visible=in_session),
        Item(gpu_label, lambda: send("gpu", report=True), enabled=up),
        Item(nyx_label, Menu(
            Item("Reiniciar Nyx", agent_restart, enabled=up),
            Item("Ir a su panel", nyx_focus, visible=nyx_in_herdr),
            Item("Sesión nueva", lambda: send("session", report=True),
                 visible=lambda _i=None: session_item_visible(current["status"])),
        ), visible=lambda _i=None: bool((current["status"] or {}).get("nyx"))),
        Menu.SEPARATOR,
        Item("Configuración", lambda: open_path(str(config.ensure_config()))),
        Item("Ver log", lambda: open_path(str(config.LOG_PATH))),
        Item("Reiniciar nyx", restart),
        Item("Cerrar icono", lambda icon, _i: icon.stop()),
    )
    icon = pystray.Icon("nyx", icon_image("down"), "nyx", menu)

    def poll(icon):
        icon.visible = True
        last_ok = time.monotonic()
        while True:
            st = fetch_status()
            if st is not None:
                last_ok = time.monotonic()
            elif time.monotonic() - last_ok > GIVE_UP_AFTER:
                icon.stop()  # el servicio se fue: el nuevo arrancará su propio icono
                return
            new = state_of(st)
            sess_changed = bool((st or {}).get("session")) != bool((current["status"] or {}).get("session"))
            current["status"] = st
            if new != current["state"] or sess_changed:
                current["state"] = new
                icon.icon = icon_image(new)
                icon.title = title_text()
                icon.update_menu()
            time.sleep(0.5 if new in ("recording", "busy", "speaking") else 1.0)

    icon.run(setup=poll)
    return 0
