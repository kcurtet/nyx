"""Icono en la bandeja del sistema (`jerga tray`).

Proceso aparte del servicio: el widget usa GTK4 y AppIndicator usa GTK3, que no pueden
convivir en el mismo proceso. Habla con el servicio por el canal de control (status,
toggle, read, hush, transcribe…) y se cierra solo si el servicio desaparece.

Color del icono: gris = listo · rojo = grabando · azul = transcribiendo/cargando ·
morado = leyendo · naranja = sin servicio.
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
    "down": (255, 159, 10),
}
LABELS = {
    "idle": "lista",
    "recording": "grabando…",
    "busy": "trabajando…",
    "speaking": "leyendo en voz alta",
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
    if st.get("busy") or not st.get("stt_ready"):
        return "busy"
    return "idle"


def fetch_status() -> dict | None:
    try:
        return json.loads(send_command("status", timeout=3))
    except (OSError, ValueError):
        return None


def notify(title: str, body: str = "") -> None:
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "jerga", "-i", "audio-input-microphone", title, body])


def pick_files() -> list[str]:
    """Selector de ficheros nativo (kdialog/zenity en Linux, Tk en Windows)."""
    filt = "*.mp3 *.wav *.ogg *.opus *.oga *.m4a *.aac *.flac *.mp4 *.mkv *.webm *.mov"
    start = os.path.expanduser("~/Descargas") if os.path.isdir(os.path.expanduser("~/Descargas")) else os.path.expanduser("~")
    if shutil.which("kdialog"):
        r = subprocess.run(["kdialog", "--title", "Transcribir con jerga", "--multiple", "--separate-output",
                            "--getopenfilename", start, f"Audio y vídeo ({filt})"], capture_output=True, text=True)
        return [line for line in r.stdout.splitlines() if line.strip()]
    if shutil.which("zenity"):
        r = subprocess.run(["zenity", "--file-selection", "--multiple", "--separator=\n", "--title=Transcribir con jerga",
                            f"--filename={start}/", f"--file-filter=Audio y vídeo | {filt}"], capture_output=True, text=True)
        return [line for line in r.stdout.splitlines() if line.strip()]
    from tkinter import Tk, filedialog

    root = Tk()
    root.withdraw()
    files = list(filedialog.askopenfilenames(title="Transcribir con jerga", initialdir=start))
    root.destroy()
    return files


def open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path])


def jerga_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "jerga", *args]


def main() -> int:
    if sys.platform.startswith("linux"):
        os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")
    try:
        import pystray
    except ImportError:
        print("jerga tray: falta pystray (pip install pystray)", file=sys.stderr)
        return 1
    from pystray import Menu
    from pystray import MenuItem as Item

    current = {"state": "down", "status": None}

    def send(cmd: str) -> None:
        try:
            send_command(cmd)
        except OSError:
            notify("jerga no está en marcha")

    def transcribe(_icon=None, _item=None):
        def work():
            files = pick_files()
            if not files:
                return
            notify("Transcribiendo…", "\n".join(os.path.basename(f) for f in files))
            r = subprocess.run(jerga_cmd("transcribe", *files), capture_output=True, text=True)
            lines = [line for line in r.stderr.splitlines() if line.startswith(("✔", "✘"))]
            notify("Transcripción terminada" if r.returncode == 0 else "Transcripción con errores", "\n".join(lines)[:400])
            done = [line.split("→ ", 1)[1].split("  [")[0] for line in lines if line.startswith("✔") and "→ " in line]
            if len(done) == 1:
                open_path(done[0])

        threading.Thread(target=work, daemon=True).start()

    def trinity_start(_icon=None, _item=None):
        def work():
            r = subprocess.run(jerga_cmd("trinity", "restart"), capture_output=True, text=True)
            notify("Trinity", (r.stdout or r.stderr).strip()[:300])
        threading.Thread(target=work, daemon=True).start()

    def trinity_label(_item=None) -> str:
        t = (current["status"] or {}).get("trinity") or {}
        if not t:
            return "Trinity"
        if t.get("backend") is None:
            return "Trinity · no disponible"
        state = {"idle": "lista", "working": "trabajando", "blocked": "esperando tu aprobación",
                 "done": "lista", None: "arrancando…"}.get(t.get("state"), t.get("state"))
        where = "herdr" if t["backend"] == "herdr" else "segundo plano"
        return f"Trinity · {state} ({where})"

    def trinity_in_herdr(_item=None) -> bool:
        return ((current["status"] or {}).get("trinity") or {}).get("backend") == "herdr"

    def trinity_focus(_icon=None, _item=None):
        if shutil.which("herdr"):
            subprocess.Popen(["herdr", "agent", "focus", "trinity"])

    def restart(_icon=None, _item=None):
        if shutil.which("systemctl"):
            subprocess.Popen(["systemctl", "--user", "restart", "jerga"])
            notify("Reiniciando jerga…")

    def title_text(_item=None) -> str:
        st = current["status"]
        if st and st.get("session"):
            return f"jerga · grabando sesión ({st['session']['kind']}) {stamp_s(st['session']['elapsed'])}"
        base = f"jerga · {LABELS[current['state']]}"
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

    def speak_action(_icon=None, _item=None):
        st = current["status"] or {}
        send("hush" if st.get("speaking") else "read")

    up = lambda _item=None: current["state"] != "down"  # noqa: E731
    in_session = lambda _item=None: bool((current["status"] or {}).get("session"))  # noqa: E731
    no_session = lambda _item=None: up() and not in_session()  # noqa: E731

    def record(*flags):
        def go(_icon=None, _item=None):
            r = subprocess.run(jerga_cmd("record", *flags), capture_output=True, text=True)
            if r.returncode != 0:
                notify("No se pudo grabar", (r.stderr or r.stdout).strip()[:300])
        return go

    def record_stop(_icon=None, _item=None):
        def work():
            r = subprocess.run(jerga_cmd("record", "stop"), capture_output=True, text=True)
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
        Item(trinity_label, Menu(
            Item("Reiniciar Trinity", trinity_start, enabled=up),
            Item("Ir a su panel", trinity_focus, visible=trinity_in_herdr),
        ), visible=lambda _i=None: bool((current["status"] or {}).get("trinity"))),
        Menu.SEPARATOR,
        Item("Configuración", lambda: open_path(str(config.ensure_config()))),
        Item("Ver log", lambda: open_path(str(config.LOG_PATH))),
        Item("Reiniciar jerga", restart),
        Item("Cerrar icono", lambda icon, _i: icon.stop()),
    )
    icon = pystray.Icon("jerga", icon_image("down"), "jerga", menu)

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
