"""Preparación del entorno antes de cargar CUDA / GTK.

Linux: las librerías se resuelven al arrancar el proceso, así que nos
re-ejecutamos una vez con LD_LIBRARY_PATH (cuBLAS/cuDNN de pip) y
LD_PRELOAD (gtk4-layer-shell debe cargarse antes que libwayland-client).

Windows: basta con añadir los directorios de DLLs de CUDA.
"""
from __future__ import annotations

import ctypes.util
import os
import sys
from pathlib import Path

_FLAG = "NYX_ENV_READY"


def nvidia_dirs(sub: str) -> list[str]:
    out = []
    for p in sys.path:
        base = Path(p) / "nvidia"
        if base.is_dir():
            out += [str(d) for d in sorted(base.glob(f"*/{sub}")) if d.is_dir()]
    return out


def layer_shell_lib() -> str | None:
    if not os.environ.get("WAYLAND_DISPLAY"):
        return None
    return ctypes.util.find_library("gtk4-layer-shell")


def prepare() -> None:
    if sys.platform == "win32":
        dirs = nvidia_dirs("bin")
        for d in dirs:
            os.add_dll_directory(d)
        if dirs:
            os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
        return
    if not sys.platform.startswith("linux") or os.environ.get(_FLAG):
        return
    env = dict(os.environ)
    env[_FLAG] = "1"
    libs = nvidia_dirs("lib")
    if libs:
        env["LD_LIBRARY_PATH"] = ":".join(libs + [p for p in [env.get("LD_LIBRARY_PATH")] if p])
    ls = layer_shell_lib()
    if ls and ls not in env.get("LD_PRELOAD", ""):
        env["LD_PRELOAD"] = ":".join([ls] + [p for p in [env.get("LD_PRELOAD")] if p])
    os.execve(sys.executable, [sys.executable, "-m", "nyx", *sys.argv[1:]], env)


def clean_child_env() -> dict:
    """Entorno para subprocesos (wl-copy, xclip…) sin nuestro LD_PRELOAD ni el aviso del alias."""
    env = dict(os.environ)
    env.pop("LD_PRELOAD", None)
    env.pop(_FLAG, None)
    env.pop("NYX_ALIAS", None)
    return env
