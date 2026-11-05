"""Transcribir audio/vídeo a texto: ficheros, notas de voz y sesiones grabadas.

Núcleo común: ffmpeg (cualquier formato) → Whisper con tu vocabulario técnico →
tus reemplazos → segmentos con marcas de tiempo → .md / .srt / .txt.

  jerga transcribe reunion.mp4                 → reunion.md al lado
  jerga transcribe *.ogg --format srt --out ~/notas
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 16000
MEDIA_EXT = {".mp3", ".wav", ".ogg", ".opus", ".oga", ".m4a", ".aac", ".flac", ".wma",
             ".mp4", ".mkv", ".webm", ".mov", ".avi", ".3gp"}


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None  # "Yo" / "Ellos" en grabaciones con dos fuentes


def decode(path: str | Path) -> np.ndarray:
    """Cualquier audio o vídeo → float32 mono 16 kHz."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("hace falta ffmpeg para leer audio/vídeo")
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn",
                        "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg no pudo leer {path}: {r.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768


def transcribe_audio(stt, audio: np.ndarray, fix=None, offset: float = 0.0, speaker: str | None = None) -> list[Segment]:
    """Audio largo → segmentos. `stt` es un jerga.stt.Transcriber ya cargado."""
    if audio.size < SR * 0.3:
        return []
    out = []
    for s in stt.segments(audio):
        text = s.text.strip()
        if fix:
            text = fix(text)
        if text:
            out.append(Segment(offset + s.start, offset + s.end, text, speaker))
    return out


# ------------------------------------------------------------------ formatos
def stamp(t: float, srt: bool = False) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    if srt:
        return f"{h:02d}:{m:02d}:{s:02d},{int((t - int(t)) * 1000):03d}"
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def paragraphs(segs: list[Segment], gap: float = 2.0, soft: int = 180, hard: int = 600) -> list[list[Segment]]:
    """Agrupa segmentos en párrafos. Nuevo párrafo si: cambia quien habla, hay una pausa larga,
    el párrafo pasa de `soft` caracteres y la frase anterior terminó, o pasa de `hard`."""
    out: list[list[Segment]] = []
    for s in segs:
        cur = out[-1] if out else None
        size = sum(len(x.text) for x in cur) if cur else 0
        ended = bool(cur) and cur[-1].text.rstrip().endswith((".", "?", "!", "…"))
        if (cur and s.speaker == cur[-1].speaker and s.start - cur[-1].end < gap
                and size < hard and not (ended and size >= soft)):
            cur.append(s)
        else:
            out.append([s])
    return out


def to_md(segs: list[Segment], title: str, source: str = "", duration: float | None = None) -> str:
    head = [f"# {title}", ""]
    meta = []
    if source:
        meta.append(f"Fuente: `{source}`")
    if duration:
        meta.append(f"Duración: {stamp(duration)}")
    meta.append(f"Transcrito: {time.strftime('%Y-%m-%d %H:%M')} con jerga")
    head += [" · ".join(meta), ""]
    body = []
    for p in paragraphs(segs):
        who = f"**{p[0].speaker}:** " if p[0].speaker else ""
        body.append(f"`[{stamp(p[0].start)}]` {who}{' '.join(s.text for s in p)}")
        body.append("")
    if not body:
        body = ["*(no se ha detectado voz)*", ""]
    return "\n".join(head + body)


def to_srt(segs: list[Segment]) -> str:
    blocks = []
    for i, s in enumerate(segs, 1):
        who = f"{s.speaker}: " if s.speaker else ""
        blocks.append(f"{i}\n{stamp(s.start, True)} --> {stamp(s.end, True)}\n{who}{s.text}\n")
    return "\n".join(blocks)


def to_txt(segs: list[Segment]) -> str:
    return "\n\n".join(
        (f"{p[0].speaker}: " if p[0].speaker else "") + " ".join(s.text for s in p) for p in paragraphs(segs)
    ) + "\n"


def render(segs: list[Segment], fmt: str, title: str, source: str = "", duration: float | None = None) -> str:
    if fmt == "srt":
        return to_srt(segs)
    if fmt == "txt":
        return to_txt(segs)
    return to_md(segs, title, source, duration)


# ----------------------------------------------------------------------- CLI
def load_stt(cfg: dict):
    from .postprocess import PostProcessor
    from .stt import Transcriber

    stt = Transcriber(cfg["stt"])
    stt.load()
    fix = PostProcessor(cfg["replacements"], {"enabled": False}, cfg["stt"]["vocabulary"]).apply_rules
    return stt, fix


def transcribe_file(stt, fix, path: Path, fmt: str = "md", out_dir: Path | None = None) -> tuple[Path, float, int]:
    audio = decode(path)
    segs = transcribe_audio(stt, audio, fix)
    dest = (out_dir or path.parent) / f"{path.stem}.{fmt}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(segs, fmt, path.stem, path.name, audio.size / SR), encoding="utf-8")
    return dest, audio.size / SR, len(segs)


def run_request(stt, fix, req: dict) -> dict:
    """Ejecuta una petición de transcripción (en el servicio o en local). Devuelve {rc, out, log}."""
    fmt, out_dir = req.get("format", "md"), req.get("out")
    out_dir = Path(out_dir).expanduser() if out_dir else None
    res = {"rc": 0, "out": "", "log": []}
    for name in req["files"]:
        f = Path(name)
        t0 = time.monotonic()
        try:
            if req.get("stdout"):
                audio = decode(f)
                res["out"] += render(transcribe_audio(stt, audio, fix), fmt, f.stem, f.name, audio.size / SR)
                continue
            dest, dur, n = transcribe_file(stt, fix, f, fmt, out_dir)
            res["log"].append(f"✔ {f.name} ({stamp(dur)}) → {dest}  [{time.monotonic() - t0:.1f}s, {n} segmentos]")
        except Exception as e:  # noqa: BLE001
            res["rc"] = 1
            res["log"].append(f"✘ {f.name}: {e}")
    return res


def main(args: list[str], cfg: dict) -> int:
    import json

    fmt, out_dir, to_stdout, files = "md", None, False, []
    it = iter(args)
    for a in it:
        if a in ("--format", "-f"):
            fmt = next(it, "md")
        elif a in ("--out", "-o"):
            out_dir = str(Path(next(it, ".")).expanduser().resolve())
        elif a == "--stdout":
            to_stdout = True
        else:
            files.append(Path(a).expanduser().resolve())
    if fmt not in ("md", "srt", "txt") or not files:
        print("uso: jerga transcribe FICHERO... [--format md|srt|txt] [--out DIR] [--stdout]", file=sys.stderr)
        return 2
    missing = [f for f in files if not f.is_file()]
    if missing:
        print(f"no existe: {', '.join(map(str, missing))}", file=sys.stderr)
        return 1
    req = {"files": [str(f) for f in files], "format": fmt, "out": out_dir, "stdout": to_stdout}

    from .hotkey import is_running, send_command

    if is_running():
        # El servicio ya tiene Whisper cargado en la GPU: no cargamos un segundo modelo.
        print("transcribiendo con el servicio de jerga…", file=sys.stderr)
        reply = send_command("transcribe", json.dumps(req), timeout=None)
        try:
            res = json.loads(reply)
        except json.JSONDecodeError:
            print(reply, file=sys.stderr)
            return 1
    else:
        print("cargando Whisper…", file=sys.stderr)
        stt, fix = load_stt(cfg)
        res = run_request(stt, fix, req)
    for line in res["log"]:
        print(line, file=sys.stderr)
    if res["out"]:
        sys.stdout.write(res["out"])
    return res["rc"]
