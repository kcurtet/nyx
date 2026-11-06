"""Volumen del sink por defecto con pactl (PipeWire/PulseAudio): ±10 %, mute conmutado o N fijo."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys

EXIT_OK, EXIT_ERROR = 0, 5

_USO = "uso: jerga vol [up|down|mute|N]   (N = 0-100)"
_SINK = "@DEFAULT_SINK@"
_PCT = re.compile(r"(\d+)%")
_MUTE = re.compile(r"Mute:\s*(yes|no)", re.I)


def _clamp(n: int) -> int:
    return max(0, min(100, n))


def build_cmd(orden: str) -> list[str]:
    """Comando pactl para la orden: up/down (±10 %), mute (conmuta) o N ya en 0-100."""
    if orden == "mute":
        return ["pactl", "set-sink-mute", _SINK, "toggle"]
    paso = {"up": "+10%", "down": "-10%"}.get(orden)
    if paso is None:  # N (defensivo: nunca fuera de 0-100)
        paso = f"{_clamp(int(orden))}%"
    return ["pactl", "set-sink-volume", _SINK, paso]


def _pactl(args: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def read_volume() -> str | None:
    """Volumen actual del sink por defecto («30%») según `pactl get-sink-volume`; None si no responde."""
    res = _pactl(["get-sink-volume", _SINK])
    if res is None or res.returncode != 0:
        return None
    m = _PCT.search(res.stdout)
    return f"{m.group(1)}%" if m else None


def _read_mute() -> bool | None:
    """True si el sink está muteado; None si pactl no responde."""
    res = _pactl(["get-sink-mute", _SINK])
    if res is None or res.returncode != 0:
        return None
    m = _MUTE.search(res.stdout)
    return m.group(1).lower() == "yes" if m else None


def main(argv: list[str]) -> int:
    if sys.platform == "win32":
        print("Todavía no sé controlar el volumen en Windows.")
        return EXIT_ERROR
    if shutil.which("pactl") is None:
        print("no puedo: pactl no está en PATH")
        return EXIT_ERROR
    arg = argv[0] if argv else "up"
    if arg in ("up", "down", "mute"):
        orden, aviso = arg, ""
    else:
        try:
            n = int(arg.rstrip("%"))
        except ValueError:
            print(_USO, file=sys.stderr)
            return EXIT_ERROR
        orden, aviso = str(_clamp(n)), f" (pediste {n})" if _clamp(n) != n else ""
    res = _pactl(build_cmd(orden)[1:])
    if res is None or res.returncode != 0:
        detalle = (res.stderr.strip() if res else "")[:80]
        print(f"no puedo cambiar el volumen: pactl no responde{f' — {detalle}' if detalle else ''}")
        return EXIT_ERROR
    if orden == "mute":  # conmuta: el estado real decide qué decir
        print("muteado" if _read_mute() is not False else "con sonido")
        return EXIT_OK
    vol = read_volume()
    print(f"volumen al {vol[:-1]} %{aviso}" if vol else f"volumen cambiado{aviso}")
    return EXIT_OK
