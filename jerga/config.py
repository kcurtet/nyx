"""Rutas, configuración (TOML) y log."""
from __future__ import annotations

import os
import shutil
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
    CONFIG_DIR = _dir("APPDATA", Path.home() / "AppData" / "Roaming") / "jerga"
    STATE_DIR = _dir("LOCALAPPDATA", Path.home() / "AppData" / "Local") / "jerga"
else:
    CONFIG_DIR = _dir("XDG_CONFIG_HOME", Path.home() / ".config") / "jerga"
    STATE_DIR = _dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / "jerga"

CONFIG_PATH = CONFIG_DIR / "config.toml"
LOG_PATH = STATE_DIR / "jerga.log"
EXAMPLE_PATH = Path(__file__).resolve().parent / "config.example.toml"
LEGACY_CONFIG = Path.home() / ".config" / "voice-agent" / "config.toml"

DEFAULTS: dict = {
    "hotkey": {"key": "KEY_RIGHTCTRL", "mode": "hold", "min_seconds": 0.35},
    "audio": {"samplerate": 16000, "device": None},
    "stt": {
        "model": "large-v3-turbo",
        "device": "auto",  # auto | cuda | cpu
        "compute_type": "auto",  # auto → float16 en GPU, int8 en CPU
        "language": "es",
        "beam_size": 5,
        "vocabulary": [],
    },
    "replacements": {},
    "commands": {
        # Si la frase termina con una de estas palabras, se quita y se ponen los signos.
        "question_words": ["interrogante", "signo de interrogación"],
        "exclamation_words": ["exclamación", "signo de exclamación", "punto de exclamación"],
        "spanish_open_marks": True,  # añade "¿" / "¡" al principio
        "quote_words": ["entre comillas"],
        "lowercase_words": ["en minúsculas"],
        "send_words": ["envía", "enviar"],
        "discard_words": ["borra eso", "bórralo"],
        "code_words": ["código"],
        "newline_words": ["nueva línea", "salto de línea"],
        "paragraph_words": ["punto y aparte"],
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
    "vision": {
        # jerga look: captura de pantalla → modelo de visión local (Ollama)
        "model": "lfm3-omni:latest",
        "url": "http://localhost:11434",
        "max_side": 1600,
        "timeout": 60,
        "keep_alive": "1m",  # cuánto mantiene Ollama el modelo en la GPU tras usarlo
    },
    "orders": {
        "enabled": True,
        # Si el dictado empieza por una de estas palabras, es una orden para la orquestadora.
        "wake_words": ["trinity"],
        "agent": "trinity",  # nombre del agente en herdr
        "model": "",  # modelo de pi para Trinity ("" = el que uses por defecto)
        "debug": False,  # log de la extensión de voz en ~/.local/state/jerga/voice.log
        # Arrancar solo con lo necesario (estado de herdr + pi-herdr + voz), sin tus otras extensiones/skills.
        "isolated": True,
        # Ruta a pi-herdr (paquete o index.ts). "" = el instalado con `pi install`.
        "pi_herdr": "",
    },
    "tts": {
        "enabled": True,
        "key": "ctrl+;",  # leer el texto seleccionado (otra vez: callar)
        "model": "hf://gradium/phonon-40m-es",
        "voice": "Nerea",
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
            "Claude": "clod",
            "docker compose": "dóker, compóus",
            "pipeline": "paip-láin",
            "pipelines": "paip-láins",
        },
    },
}


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
    """Imprime y guarda en el log (útil en Windows, donde jerga-gui no tiene consola)."""
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
