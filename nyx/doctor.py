"""`nyx doctor`: comprueba el equipo, función a función, y dice cómo arreglar lo que falte.

✘ = rompe algo básico (dictar, pegar, leer en voz alta, transcribir) · ! = opcional o mejorable.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
from pathlib import Path

from . import __version__, config

OK, WARN, BAD = "✔", "!", "✘"


class Report:
    def __init__(self):
        self.problems = 0
        self.warnings = 0

    def section(self, title: str):
        print(f"\n{title}")

    def ok(self, what, detail=""):
        self._line(OK, what, detail)

    def warn(self, what, detail=""):
        self.warnings += 1
        self._line(WARN, what, detail)

    def bad(self, what, detail=""):
        self.problems += 1
        self._line(BAD, what, detail)

    @staticmethod
    def _line(mark, what, detail):
        print(f"  {mark} {what}" + (f" — {detail}" if detail else ""))


def _pkg_hint(arch: str, debian: str, fedora: str = "") -> str:
    """Nombre del paquete según la distro detectada."""
    try:
        ids = Path("/etc/os-release").read_text()
    except OSError:
        ids = ""
    if any(x in ids for x in ("arch", "cachyos", "manjaro", "endeavouros")):
        return f"sudo pacman -S {arch}"
    if any(x in ids for x in ("debian", "ubuntu")):
        return f"sudo apt install {debian}"
    if "fedora" in ids and fedora:
        return f"sudo dnf install {fedora}"
    return f"instala {arch}"


def _typelib(name: str) -> bool:
    dirs = ["/usr/lib/girepository-1.0", "/usr/lib64/girepository-1.0",
            "/usr/lib/x86_64-linux-gnu/girepository-1.0", "/usr/lib/aarch64-linux-gnu/girepository-1.0"]
    dirs += [d for d in os.environ.get("GI_TYPELIB_PATH", "").split(":") if d]
    return any(Path(d, name).exists() for d in dirs)


def doctor() -> int:
    r = Report()
    from .migrate import run as migrate_run

    migrado = migrate_run()  # antes de cargar la config: no crear rutas nuevas vacías
    cfg = config.load()
    linux = config.IS_LINUX
    wl = bool(os.environ.get("WAYLAND_DISPLAY"))
    session = os.environ.get("XDG_SESSION_TYPE", "") or ("windows" if config.IS_WINDOWS else "?")
    print(f"nyx {__version__} · Python {platform.python_version()} · {platform.system()} {platform.release()}"
          f" · {session} {os.environ.get('XDG_CURRENT_DESKTOP', '')}".rstrip())
    print(f"  config: {config.ensure_config()}")
    print(f"  log:    {config.LOG_PATH}")
    for m in migrado:
        print(f"  migrado: {m}")

    # ------------------------------------------------------------- servicio
    r.section("Servicio")
    from .hotkey import is_running, send_command

    if is_running():
        try:
            st = json.loads(send_command("status"))
            r.ok(f"en marcha (nyx {st.get('version')})",
                 f"Whisper {'listo en ' + str(st.get('stt_device')) if st.get('stt_ready') else 'cargando'}"
                 f" · voz {'lista' if st.get('tts_ready') else 'no disponible'}")
        except (OSError, ValueError):
            r.ok("en marcha")
    else:
        r.warn("no está en marcha", "systemctl --user start nyx  (o ejecuta `nyx`)")

    # -------------------------------------------------------------- dictado
    r.section("Dictado")
    try:
        import ctranslate2

        n = ctranslate2.get_cuda_device_count()
        if n:
            try:
                import ctypes

                ctypes.CDLL("cublas64_12.dll" if config.IS_WINDOWS else "libcublas.so.12")
                r.ok(f"Whisper en GPU ({n} CUDA)")
            except OSError:
                r.warn("GPU detectada pero sin cuBLAS 12", "reinstala con el extra [cuda]; mientras, usará CPU")
        else:
            r.warn("sin GPU CUDA", 'usará CPU (más lento); si va lento: [stt] model = "small"')
    except Exception as e:  # noqa: BLE001
        r.bad("faster-whisper no carga", str(e))
    try:
        import sounddevice as sd

        r.ok(f"micrófono: {sd.query_devices(kind='input')['name']}")
    except Exception as e:  # noqa: BLE001
        r.bad("sin micrófono utilizable", f"{e} · {_pkg_hint('portaudio', 'libportaudio2', 'portaudio') if linux else ''}")

    if config.IS_WINDOWS:
        r.ok("tecla global con pynput")
    else:
        try:
            import evdev

            readable = sum(1 for p in evdev.list_devices() if _can_open(evdev, p))
            if readable:
                r.ok(f"tecla global: {readable} dispositivos de entrada legibles ({cfg['hotkey']['key']})")
            else:
                r.bad("no puedo leer el teclado", "sudo usermod -aG input $USER y vuelve a iniciar sesión")
            from .hotkey import ctrl_key_names, xkb_options

            opts = xkb_options()
            remap = [o for o in opts if o.startswith(("ctrl:", "caps:"))]
            if remap:
                keys = ", ".join(sorted(ctrl_key_names(opts, cfg["hotkey"].get("ctrl_keys"))))
                r.ok(f"opciones de teclado {remap}", f"en los atajos, Ctrl = {keys}")
        except ImportError:
            r.bad("python-evdev no instalado", _pkg_hint("python-evdev", "python3-evdev", "python3-evdev"))

    # ---------------------------------------------------- pegar en el cursor
    if config.IS_WINDOWS:
        r.ok("pegar: portapapeles + Ctrl+V")
    else:
        if not wl and not os.environ.get("DISPLAY"):
            r.warn("no hay sesión gráfica (ni WAYLAND_DISPLAY ni DISPLAY)")
        elif wl and shutil.which("wl-copy"):
            r.ok("portapapeles: wl-clipboard")
        elif not wl and (shutil.which("xclip") or shutil.which("xsel")):
            r.ok("portapapeles: xclip/xsel")
        else:
            r.bad("sin herramienta de portapapeles", _pkg_hint("wl-clipboard" if wl else "xclip", "wl-clipboard" if wl else "xclip"))
        if os.access("/dev/uinput", os.W_OK):
            r.ok("teclado virtual (/dev/uinput) para pulsar Shift+Insert")
        elif shutil.which("ydotool") or (not wl and shutil.which("xdotool")):
            r.warn("/dev/uinput no escribible", "usaré ydotool/xdotool")
        else:
            r.bad("no puedo simular Shift+Insert", "ejecuta install.sh (regla udev de /dev/uinput) o instala ydotool")

    # ------------------------------------------------------- leer en voz alta
    r.section("Leer en voz alta")
    if not cfg["tts"]["enabled"]:
        r.warn("desactivado", "[tts] enabled = true")
    else:
        try:
            import ptts  # noqa: F401

            r.ok(f"voz phonon · {cfg['tts']['voice']} · tecla {cfg['tts']['key']} (o «léeme esto»)")
        except Exception as e:  # noqa: BLE001
            r.bad("ptts no instalado", str(e))
        try:
            import sounddevice as sd

            r.ok(f"salida de audio: {sd.query_devices(kind='output')['name']}")
        except Exception as e:  # noqa: BLE001
            r.warn("sin salida de audio", str(e))

    # ------------------------------------------------------------ transcribir
    r.section("Transcribir")
    if shutil.which("ffmpeg"):
        r.ok("ffmpeg: ficheros de audio/vídeo y notas de voz")
    else:
        r.bad("sin ffmpeg: nyx transcribe y las notas de voz no funcionarán",
              _pkg_hint("ffmpeg", "ffmpeg", "ffmpeg-free") if linux else "winget install Gyan.FFmpeg")
    if linux:
        if shutil.which("parec"):
            r.ok("audio del sistema (nyx record --system/--both)")
        else:
            r.warn("sin parec: no se puede grabar el audio del PC", _pkg_hint("libpulse", "pulseaudio-utils", "pulseaudio-utils"))
    if cfg["notes"]["enabled"]:
        from .session import notes_dirs

        dirs = [d for d in notes_dirs(cfg["notes"], cfg["record"]) if Path(os.path.expanduser(d)).is_dir()]
        if dirs:
            r.ok(f"notas de voz: deja los audios en {', '.join(dirs)}")
        else:
            r.warn("notas de voz: ninguna carpeta vigilada existe", f"[notes] dirs = {cfg['notes']['dirs']}")

    # ------------------------------------------------------------- interfaz
    r.section("Interfaz")
    from .ui import available

    av = available()
    if av[0] != "none":
        r.ok(f"widget: {av[0]}")
    else:
        r.warn("sin widget", "instala gtk4-layer-shell + python-gobject (KDE/Sway/Hyprland) o tk")
    if cfg["tray"]["enabled"]:
        import importlib.util

        if importlib.util.find_spec("pystray") is None:
            r.warn("icono de bandeja: falta pystray", "reinstala nyx")
        elif linux and not (_typelib("AyatanaAppIndicator3-0.1.typelib") or _typelib("AppIndicator3-0.1.typelib")):
            r.warn("icono de bandeja: falta AppIndicator",
                   _pkg_hint("libayatana-appindicator", "gir1.2-ayatanaappindicator3-0.1", "libayatana-appindicator-gtk3"))
        else:
            r.ok("icono de bandeja")
    if linux:
        if shutil.which("notify-send"):
            r.ok("notificaciones (notify-send)")
        else:
            r.warn("sin notify-send: no verás avisos de notas de voz ni sesiones", _pkg_hint("libnotify", "libnotify-bin", "libnotify"))
        if not (shutil.which("kdialog") or shutil.which("zenity")):
            r.warn("sin kdialog/zenity: «Transcribir fichero…» usará un selector básico", _pkg_hint("zenity", "zenity", "zenity"))

    # ------------------------------------------------------- ver la pantalla
    r.section("Ver la pantalla (nyx look)")
    vc = cfg["vision"]
    try:
        import httpx

        tags = httpx.get(vc["url"].rstrip("/") + "/api/tags", timeout=2).json().get("models", [])
        names = {m.get("name", "") for m in tags} | {m.get("name", "").split(":")[0] for m in tags}
        if vc["model"] in names or vc["model"].split(":")[0] in names:
            r.ok(f"Ollama con {vc['model']}")
        else:
            r.warn(f"Ollama responde pero falta {vc['model']}", f"ollama pull {vc['model'].split(':')[0]}")
    except Exception:  # noqa: BLE001
        r.warn("Ollama no responde (opcional)", "instala Ollama y: ollama pull lfm3-omni")
    if linux and not any(shutil.which(t) for t in ("spectacle", "grim", "gnome-screenshot", "maim", "scrot")):
        r.warn("sin herramienta de captura", "instala spectacle (KDE), grim (wlroots) o gnome-screenshot")

    # ---------------------------------------------------------------- Trinity
    oc = cfg["orders"]
    if oc["enabled"]:
        r.section(f"{oc['agent'].capitalize()} (órdenes por voz)")
        from .orders import Orchestrator, _ext_file, _pi_agent_dir, choose_backend

        kind, reason = choose_backend(oc)
        if kind is None:
            r.warn("no disponible", reason)
        elif kind == "pi":
            r.ok("pi en segundo plano (sin herdr)", "funciona igual, pero sin paneles ni avisos de tus agentes de herdr")
        else:
            r.ok("herdr + pi", "en su propio workspace; vigila a tus agentes con pi-herdr")
            pkg = Path(os.path.expanduser(oc["pi_herdr"])) if oc.get("pi_herdr") else \
                _pi_agent_dir() / "git" / "github.com" / "kcurtet" / "pi-herdr"
            if _ext_file(pkg):
                r.ok(f"pi-herdr: {pkg}")
            else:
                r.warn("pi-herdr no encontrado: sin avisos de agentes", "pi install github:kcurtet/pi-herdr")
            st = Orchestrator(oc).status()
            if st:
                r.ok(f"{oc['agent']} en marcha ({st})", f"dile «{oc['agent'].capitalize()}, …»")
            else:
                r.warn(f"{oc['agent']} no está en marcha", "el servicio la arranca solo; o: nyx agent")

    # --------------------------------------------------------- LLM opcional
    if cfg["llm"]["enabled"]:
        r.section("Corrección con LLM")
        try:
            import httpx

            httpx.get(cfg["llm"]["url"], timeout=2)
            r.ok(f"Ollama responde en {cfg['llm']['url']}")
        except Exception as e:  # noqa: BLE001
            r.warn("Ollama no responde", str(e))

    print()
    if r.problems:
        print(f"{r.problems} problema(s) por resolver, {r.warnings} aviso(s).")
    elif r.warnings:
        print(f"Todo lo básico está listo. {r.warnings} aviso(s) sobre extras opcionales.")
    else:
        print("Todo listo.")
    return 1 if r.problems else 0


def _can_open(evdev, path) -> bool:
    try:
        evdev.InputDevice(path)
        return True
    except OSError:
        return False
