"""Rutas, configuración (TOML) y log."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def _dir(env: str, fallback: Path) -> Path:
    v = os.environ.get(env)
    return Path(v) if v else fallback


if IS_WINDOWS:
    CONFIG_DIR = _dir("APPDATA", Path.home() / "AppData" / "Roaming") / "nyx"
    STATE_DIR = _dir("LOCALAPPDATA", Path.home() / "AppData" / "Local") / "nyx"
else:
    CONFIG_DIR = _dir("XDG_CONFIG_HOME", Path.home() / ".config") / "nyx"
    STATE_DIR = _dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / "nyx"

CONFIG_PATH = CONFIG_DIR / "config.toml"
LOG_PATH = STATE_DIR / "nyx.log"
EXAMPLE_PATH = Path(__file__).resolve().parent / "config.example.toml"
LEGACY_CONFIG = Path.home() / ".config" / "voice-agent" / "config.toml"

DEFAULTS: dict = {
    "hotkey": {
        "key": "KEY_RIGHTCTRL", "mode": "hold", "min_seconds": 0.35,
        # Teclas físicas extra que cuentan como Ctrl en los atajos (las de xkb como ctrl:swapcaps
        # se detectan solas en KDE, GNOME y wlroots). Ej.: ["KEY_CAPSLOCK"]
        "ctrl_keys": [],
    },
    "audio": {"samplerate": 16000, "device": None},
    "stt": {
        "model": "large-v3-turbo",
        "device": "auto",  # auto | cuda | cpu
        "compute_type": "auto",  # auto → float16 en GPU, int8 en CPU
        "language": "es",
        "beam_size": 5,
        # Palabras de los comandos «ruta» (símbolos de paths), «vim» (frases del mapa)
        # y «programar» (símbolos y números), para que Whisper las espere.
        "vocabulary": [
            "ruta", "tilde", "barra", "contrabarra", "barra invertida", "punto", "guion",
            "guion bajo", "bajo", "dos puntos", "espacio", "arroba",
            "vim", "modo vim", "bim", "modo bim", "beam", "modo beam", "borrar línea", "borrar palabra", "borrar carácter",
            "copiar línea", "pegar", "deshacer", "rehacer", "insertar",
            "insertar al final", "insertar línea abajo", "insertar línea arriba",
            "siguiente palabra", "buscar", "buscar y reemplazar", "línea de comando",
            "guardar", "salir", "guardar y salir", "forzar salir",
            "principio del fichero", "final del fichero",
            "programar", "modo programar", "es igual a", "no igual a", "distinto de",
            "mayor que", "menor que", "mayor o igual", "menor o igual", "flecha",
            "entre comillas", "cierra comillas", "entre comillas simples",
            "cierra comillas simples", "punto y coma", "coma", "más", "por", "entre",
            "por ciento", "barra vertical", "ampersand",
            "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
            "nueve", "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis",
            "diecisiete", "dieciocho", "diecinueve", "veinte", "treinta", "cuarenta",
            "cincuenta", "sesenta", "setenta", "ochenta", "noventa", "cien", "mil",
        ],
    },
    "replacements": {},
    "commands": {
        # Si la frase termina con una de estas palabras, se quita y se ponen los signos.
        "question_words": ["interrogante", "signo de interrogación"],
        "exclamation_words": ["exclamación", "signo de exclamación", "punto de exclamación"],
        "spanish_open_marks": True,  # añade "¿" / "¡" al principio
        "quote_words": ["entre comillas"],
        "lowercase_words": ["en minúsculas", "minúsculas"],
        "send_words": ["envía", "enviar"],
        "discard_words": ["borra eso", "bórralo"],
        "code_words": ["código"],
        "path_words": ["ruta"],
        # «vim …»: frase → secuencia de teclas para la ventana con foco (spec 007).
        # TODAS las secuencias empiezan con esc (salva desde insert/command mode).
        # Tokens lógicos «slash»/«colon» los resuelve vim_layout; % y ! son shift+5/shift+1
        # (universales en US y ES). El mapa del usuario se MERGE con este (gana por frase).
        "vim_words": ["vim", "modo vim", "bim", "modo bim", "beam", "modo beam"],  # /bim/ fonético
        "vim_layout": "us",  # us | es (cómo se escriben / y : en tu teclado físico)
        "vim_map": {
            "borrar línea": "esc d d",
            "borrar palabra": "esc d w",
            "borrar carácter": "esc x",
            "copiar línea": "esc y y",
            "pegar": "esc p",
            "deshacer": "esc u",
            "rehacer": "esc ctrl+r",
            "insertar": "esc i",
            "insertar al final": "esc shift+a",
            "insertar línea abajo": "esc o",
            "insertar línea arriba": "esc shift+o",
            "siguiente palabra": "esc w",
            "buscar": "esc slash",
            "buscar y reemplazar": "esc colon shift+5 s slash",
            "línea de comando": "esc colon",
            "guardar": "esc colon w enter",
            "salir": "esc colon q enter",
            "guardar y salir": "esc colon w q enter",
            "forzar salir": "esc colon q shift+1 enter",
            "principio del fichero": "esc g g",
            "final del fichero": "esc shift+g",
        },
        # «programar …»: código de una línea con símbolos hablados (spec 007).
        "code_line_words": ["programar", "modo programar"],
        "newline_words": ["nueva línea", "salto de línea"],
        "paragraph_words": ["punto y aparte"],
        # Frases-orden (solo si es TODO lo que dices): leer en voz alta lo seleccionado / callar.
        "read_words": ["léeme esto", "lee esto", "léelo", "lee la selección", "léeme la selección"],
        "hush_words": ["calla", "cállate", "silencio", "para de leer"],
    },
    "llm": {
        "enabled": False,
        "url": "http://localhost:11434",
        "model": "qwen2.5:3b",
        "timeout": 4.0,
    },
    "output": {
        "method": "paste",  # paste | type | clipboard
        # Windows: ctrl+v. Linux: shift+insert (pega en terminales y apps).
        "paste_keys": "ctrl+v" if IS_WINDOWS else "shift+insert",
        "restore_clipboard": True,
        "trailing_space": True,
        "strip_final_period": False,
    },
    "ui": {"backend": "auto"},  # auto | gtk | tk | none
    "tray": {"enabled": True},  # icono en la bandeja del sistema
    "record": {
        "dir": "",  # "" = ~/Documentos/nyx (carpeta de documentos de tu sistema)
        "labels": ["Yo", "Ellos"],  # micrófono / audio del sistema cuando se graban los dos
        "mic_device": None,
    },
    "transcribe": {
        # Ficheros más largos que esto se transcriben por bloques cortados en silencios:
        # el dictado no se queda bloqueado (pasa delante entre bloques) y Whisper no entra en bucle.
        "long_after_s": 600,
        "block_s": 300,
    },
    "notes": {
        # Transcribe las notas de voz NUEVAS que TÚ dejes en estas carpetas (deja el .md al lado).
        # [] = solo ~/Documentos/nyx/notas (se crea sola). No pongas Descargas: ahí cae de todo.
        "enabled": True,
        "dirs": [],
        "extensions": [".ogg", ".opus", ".oga", ".m4a"],
    },
    "vision": {
        # nyx look: captura de pantalla → modelo de visión local (Ollama)
        "model": "lfm3-omni:latest",
        "url": "http://localhost:11434",
        "max_side": 1600,
        "timeout": 60,
        "keep_alive": "1m",  # cuánto mantiene Ollama el modelo en la GPU tras usarlo
    },
    "orders": {
        "enabled": True,
        # Si el dictado empieza por una de estas palabras, es una orden para la orquestadora.
        "wake_words": ["nyx"],
        "agent": "nyx-agent",  # nombre del agente en herdr (y de su workspace)
        "model": "",  # modelo de pi para Nyx ("" = el que uses por defecto)
        "debug": False,  # log de la extensión de voz en ~/.local/state/nyx/voice.log
        # Dónde vive la orquestadora. herdr: su propio workspace (la ves trabajar).
        # pi: en segundo plano dentro del servicio. efimero: nada encendido — cada orden
        # arranca un pi one-shot (memoria en el fichero de sesión; sesión nueva cada día),
        # responde en voz alta y muere. auto: herdr si puede; si no, pi en segundo plano.
        "backend": "auto",
        "autostart": True,  # el servicio la arranca y la vuelve a levantar si se cae
        # Extensiones de pi extra para Nyx (nombre de paquete instalado con `pi install`, o ruta).
        # pi-web-access: buscar en internet y leer páginas. Las que no estén instaladas se omiten.
        "extensions": ["pi-web-access"],
        # Arrancar solo con lo necesario (estado de herdr + pi-herdr + voz), sin tus otras extensiones/skills.
        "isolated": True,
        "topology": "workspace",  # workspace propio (recomendado) o "tab" en el workspace actual
        # Ruta a pi-herdr (paquete o index.ts). "" = el instalado con `pi install`.
        "pi_herdr": "",
    },
    "tts": {
        "enabled": True,
        "key": "ctrl+0",  # leer el texto seleccionado (otra vez: callar). También por voz: «léeme esto»
        "model": "hf://gradium/phonon-40m-es",
        "voice": "Nerea",
        # copy: pulsa "copiar" (Ctrl+Insert) y lee el portapapeles (fiable en todas las apps)
        # primary: solo la selección primaria de Linux (sin pulsar nada; algunas apps no la actualizan)
        "selection": "copy",
        "quant": "q8_0",
        "max_chars": 4000,
        # Cómo debe sonar cada término (afinado a oído con la voz Nerea).
        "lexicon": {
            "git": "guit",
            "kubectl": "kiub ci ti el",
            "el CI/CD": "la integración continua",
            "del CI/CD": "de la integración continua",
            "al CI/CD": "a la integración continua",
            "CI/CD": "integración continua",
            "YAML": "yámal",
            "JSON": "yéison",
            "Claude": "clod",
            "docker compose": "dóker, compóus",
            "pipeline": "paip-láin",
            "pipelines": "paip-láins",
        },
    },
}


def docs_root() -> Path:
    """Carpeta de documentos del usuario (xdg-user-dir si está; si no, ~/Documents)."""
    docs = None
    if shutil.which("xdg-user-dir"):
        docs = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True).stdout.strip()
    return Path(docs or Path.home() / "Documents")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def ensure_config() -> Path:
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        src = LEGACY_CONFIG if LEGACY_CONFIG.exists() else EXAMPLE_PATH
        shutil.copy(src, CONFIG_PATH)
    return CONFIG_PATH


def load() -> dict:
    ensure_config()
    with open(CONFIG_PATH, "rb") as f:
        user = tomllib.load(f)
    return _merge(DEFAULTS, user)


_log_file = None


def log(*parts) -> None:
    """Imprime y guarda en el log (útil en Windows, donde nyx-gui no tiene consola)."""
    global _log_file
    msg = " ".join(str(p) for p in parts)
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001  (sin consola en pythonw)
        pass
    try:
        if _log_file is None:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            _log_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        _log_file.write(line + "\n")
    except OSError:
        pass
