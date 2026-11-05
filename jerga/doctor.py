"""`jerga doctor`: comprueba el equipo y dice cómo arreglar lo que falte."""
from __future__ import annotations

import os
import platform
import shutil
import sys

from . import __version__, config

OK, WARN, BAD = "✔", "!", "✘"


def _line(mark, what, detail=""):
    print(f"  {mark} {what}" + (f" — {detail}" if detail else ""))


def doctor() -> int:
    problems = 0
    print(f"jerga {__version__} · Python {platform.python_version()} · {platform.system()} {platform.release()}")
    session = os.environ.get("XDG_SESSION_TYPE", "") or ("windows" if config.IS_WINDOWS else "?")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    print(f"  sesión: {session} {desktop}".rstrip())
    print(f"  config: {config.ensure_config()}")
    print(f"  log:    {config.LOG_PATH}\n")

    # ---- Whisper / GPU
    print("Reconocimiento de voz")
    try:
        import ctranslate2

        n = ctranslate2.get_cuda_device_count()
        if n:
            _line(OK, f"GPU CUDA detectada ({n})")
            try:
                import ctypes

                ctypes.CDLL("cublas64_12.dll" if config.IS_WINDOWS else "libcublas.so.12")
                _line(OK, "cuBLAS 12 cargable")
            except OSError:
                _line(WARN, "cuBLAS 12 no encontrado", "reinstala con el extra [cuda]; mientras tanto usará CPU")
        else:
            _line(WARN, "sin GPU CUDA", "usará CPU (int8): más lento. Considera stt.model = \"small\" o \"medium\"")
    except Exception as e:  # noqa: BLE001
        problems += 1
        _line(BAD, "faster-whisper/ctranslate2 no importa", str(e))

    # ---- Micrófono
    print("Micrófono")
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        _line(OK, f"entrada por defecto: {dev['name']}")
    except Exception as e:  # noqa: BLE001
        problems += 1
        hint = "instala portaudio (libportaudio2 / portaudio)" if config.IS_LINUX else ""
        _line(BAD, "sin micrófono utilizable", f"{e} {hint}".strip())

    # ---- Tecla global
    print("Tecla global")
    if config.IS_WINDOWS:
        try:
            import pynput  # noqa: F401

            _line(OK, "pynput disponible")
        except Exception as e:  # noqa: BLE001
            problems += 1
            _line(BAD, "pynput no disponible", str(e))
    else:
        try:
            import evdev

            readable = 0
            for p in evdev.list_devices():
                try:
                    evdev.InputDevice(p)
                    readable += 1
                except OSError:
                    pass
            if readable:
                _line(OK, f"{readable} dispositivos de entrada legibles")
            else:
                problems += 1
                _line(BAD, "no puedo leer /dev/input",
                      "sudo usermod -aG input $USER y vuelve a iniciar sesión (o usa `jerga toggle` en un atajo)")
        except ImportError:
            problems += 1
            _line(BAD, "python-evdev no instalado", "instala python3-evdev / python-evdev")

    # ---- Pegar en el cursor
    print("Escribir en el cursor")
    if config.IS_WINDOWS:
        _line(OK, "portapapeles + Ctrl+V (pyperclip/pynput)")
    else:
        wl = bool(os.environ.get("WAYLAND_DISPLAY"))
        if not wl and not os.environ.get("DISPLAY"):
            _line(WARN, "no hay sesión gráfica (ni WAYLAND_DISPLAY ni DISPLAY)")
        elif wl and shutil.which("wl-copy"):
            _line(OK, "portapapeles: wl-clipboard")
        elif not wl and (shutil.which("xclip") or shutil.which("xsel")):
            _line(OK, "portapapeles: xclip/xsel")
        else:
            problems += 1
            _line(BAD, "sin herramienta de portapapeles", "instala wl-clipboard (Wayland) o xclip (X11)")
        if os.access("/dev/uinput", os.W_OK):
            _line(OK, "teclado virtual: /dev/uinput escribible")
        elif shutil.which("ydotool") or (not wl and shutil.which("xdotool")):
            _line(WARN, "/dev/uinput no escribible", "usaré ydotool/xdotool")
        else:
            problems += 1
            _line(BAD, "no puedo simular Shift+Insert",
                  "ejecuta install.sh (añade regla udev para /dev/uinput) o instala ydotool")

    # ---- Widget
    print("Widget")
    from .ui import available

    av = available()
    _line(OK if av[0] != "none" else WARN, f"backend: {av[0]}", "disponibles: " + ", ".join(av))
    if av[0] == "none" and config.IS_LINUX:
        print("     → instala gtk4-layer-shell + python-gobject (KDE/Sway/Hyprland) o python3-tk")

    cfg = config.load()

    # ---- Voz
    print("Leer en voz alta")
    if not cfg["tts"]["enabled"]:
        _line(WARN, "desactivado en la config")
    else:
        try:
            import ptts  # noqa: F401

            _line(OK, f"phonon disponible · voz {cfg['tts']['voice']} · tecla {cfg['tts']['key']}")
        except Exception as e:  # noqa: BLE001
            problems += 1
            _line(BAD, "ptts no instalado", str(e))
        try:
            import sounddevice as sd

            _line(OK, f"salida de audio: {sd.query_devices(kind='output')['name']}")
        except Exception as e:  # noqa: BLE001
            _line(WARN, "sin salida de audio", str(e))

    # ---- LLM opcional
    if cfg["llm"]["enabled"]:
        print("Corrección con LLM")
        try:
            import httpx

            httpx.get(cfg["llm"]["url"], timeout=2)
            _line(OK, f"Ollama responde en {cfg['llm']['url']}")
        except Exception as e:  # noqa: BLE001
            _line(WARN, "Ollama no responde", str(e))

    print()
    print("Todo listo." if not problems else f"{problems} problema(s) por resolver.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(doctor())
