"""`nyx look "pregunta"`: captura la pantalla y la entiende un modelo de visión local (lfm3-omni).

Pensado para Nyx: «Nyx, mira mi pantalla, ¿qué error sale?» → `nyx look "¿qué error sale?"`.
Todo en local vía Ollama: la captura nunca sale del equipo.

Capturas: spectacle (KDE) · grim (wlroots) · gnome-screenshot · maim/scrot (X11) · PIL (Windows).
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .platform_env import clean_child_env

# target: "monitor" (el del cursor) · "window" (ventana activa) · "all" (todos los monitores)
_CAPTURE = {
    "spectacle": {"monitor": ["-b", "-n", "-m"], "window": ["-b", "-n", "-a"], "all": ["-b", "-n", "-f"]},
}

PROMPT = (
    "Eres los ojos de una asistente de voz para un programador. Mira la captura de pantalla y responde "
    "en español, en 1-3 frases claras, a esto: {q}\n"
    "Si hay texto relevante (errores, rutas, nombres), cítalo literalmente. Si no se ve lo que se pregunta, dilo."
)


def capture(target: str = "monitor") -> Path:
    out = Path(tempfile.mkstemp(prefix="nyx-look-", suffix=".png")[1])
    env = clean_child_env()
    if sys.platform == "win32":
        from PIL import ImageGrab  # pillow: solo en Windows

        ImageGrab.grab(all_screens=(target == "all")).save(out)
        return out
    if shutil.which("spectacle"):
        cmd = ["spectacle", *_CAPTURE["spectacle"][target], "-o", str(out)]
    elif shutil.which("grim"):
        cmd = ["grim", str(out)]
    elif shutil.which("gnome-screenshot"):
        cmd = ["gnome-screenshot", *(["-w"] if target == "window" else []), "-f", str(out)]
    elif shutil.which("maim"):
        cmd = ["maim", str(out)]
    elif shutil.which("scrot"):
        cmd = ["scrot", "-o", str(out)]
    else:
        raise RuntimeError("no hay herramienta de captura (instala spectacle, grim, gnome-screenshot o maim)")
    subprocess.run(cmd, check=True, timeout=15, env=env)
    for _ in range(20):  # spectacle escribe el fichero tras salir
        if out.exists() and out.stat().st_size > 0:
            break
        time.sleep(0.1)
    return out


def shrink(png: Path, max_side: int) -> bytes:
    """Reduce la captura (los modelos pequeños no ganan nada con 4K y tardan más)."""
    tool = shutil.which("magick") or shutil.which("convert")
    if tool:
        r = subprocess.run([tool, str(png), "-resize", f"{max_side}x{max_side}>", "-quality", "85", "jpg:-"],
                           capture_output=True, timeout=20)
        if r.returncode == 0 and r.stdout:
            return r.stdout
    if shutil.which("ffmpeg"):
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(png), "-vf",
                            f"scale='min({max_side},iw)':-2", "-f", "mjpeg", "-"], capture_output=True, timeout=20)
        if r.returncode == 0 and r.stdout:
            return r.stdout
    return png.read_bytes()


def ask(image: bytes, question: str, cfg: dict) -> str:
    import httpx

    r = httpx.post(
        cfg["url"].rstrip("/") + "/api/chat",
        json={
            "model": cfg["model"],
            "stream": False,
            "keep_alive": cfg.get("keep_alive", "1m"),  # no acaparar la GPU (Whisper la necesita)
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT.format(q=question),
                          "images": [base64.b64encode(image).decode()]}],
        },
        timeout=cfg.get("timeout", 60),
    )
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["message"]["content"].strip()


def look(question: str, cfg: dict, target: str = "monitor", keep: bool = False) -> str:
    png = capture(target)
    try:
        return ask(shrink(png, cfg.get("max_side", 1600)), question or "¿Qué hay en la pantalla?", cfg)
    finally:
        if keep:
            print(f"(captura: {png})", file=sys.stderr)
        else:
            png.unlink(missing_ok=True)


def main(args: list[str], cfg: dict) -> int:
    target = "monitor"
    keep = False
    rest = []
    for a in args:
        if a in ("--window", "-w"):
            target = "window"
        elif a in ("--all", "-a"):
            target = "all"
        elif a == "--keep":
            keep = True
        else:
            rest.append(a)
    question = " ".join(rest).strip()
    if not question and not sys.stdin.isatty():
        question = sys.stdin.read().strip()
    try:
        t0 = time.monotonic()
        answer = look(question, cfg, target, keep)
    except Exception as e:  # noqa: BLE001
        print(f"nyx look: {e}", file=sys.stderr)
        return 1
    print(answer)
    if os.environ.get("NYX_DEBUG"):
        print(f"({time.monotonic() - t0:.1f}s)", file=sys.stderr)
    return 0
