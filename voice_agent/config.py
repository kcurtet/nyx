"""Carga de configuración (TOML) con valores por defecto."""
from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "voice-agent"
CONFIG_PATH = CONFIG_DIR / "config.toml"
EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "config.example.toml"

DEFAULTS: dict = {
    "hotkey": {"key": "KEY_RIGHTCTRL", "mode": "hold", "min_seconds": 0.35},
    "audio": {"samplerate": 16000, "device": None},
    "stt": {
        "model": "large-v3-turbo",
        "device": "cuda",
        "compute_type": "float16",
        "language": "es",
        "beam_size": 5,
        "vocabulary": [],
    },
    "replacements": {},
    "llm": {
        "enabled": False,
        "url": "http://localhost:11434",
        "model": "qwen2.5:3b",
        "timeout": 4.0,
    },
    "output": {
        "method": "paste",  # paste | type | clipboard
        "paste_keys": "shift+insert",
        "restore_clipboard": True,
        "trailing_space": True,
        "strip_final_period": False,
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


def load() -> dict:
    if not CONFIG_PATH.exists() and EXAMPLE_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(EXAMPLE_PATH, CONFIG_PATH)
    user = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            user = tomllib.load(f)
    return _merge(DEFAULTS, user)
