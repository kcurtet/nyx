"""Texto → voz con phonon (ptts): normalizador para texto técnico + lexicón + streaming.

El normalizador prepara texto pensado para leerse, no para verse:
  - bloques de código  → "Bloque de código en python."
  - `código en línea`  → su contenido
  - [enlace](url)      → el texto del enlace;  https://github.com/x → "un enlace a github.com"
  - /ruta/larga/a/fichero.py → "fichero.py"
  - Markdown (#, **, -, tablas) y emojis → fuera
El lexicón reescribe los términos como suenan ("kubectl" → "kiub ci ti el").
"""
from __future__ import annotations

import re
import threading
import unicodedata

import numpy as np

from .config import log

# --------------------------------------------------------------- normalizar
_CODE_BLOCK = re.compile(r"```[ \t]*([\w+#.-]*)[^\n]*\n.*?(?:```|\Z)", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_URL = re.compile(r"\bhttps?://(?:www\.)?([^/\s)]+)[^\s)]*")
# rutas: empiezan por / ~/ ./ ../ o tienen 2+ barras (así "CI/CD" o "y/o" no cuentan)
_PATH = re.compile(r"(?<![\w/])(?:~|\.{1,2})?/(?:[\w.@+-]+/)*([\w.@+-]+)|(?<![\w/])(?:[\w.@+-]+/){2,}([\w.@+-]+)")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$|^\s*\|?\s*:?-{3,}")


def _strip_emoji(s: str) -> str:
    return "".join(c for c in s if unicodedata.category(c) not in ("So", "Cs") and c not in "️‍")


def normalize(text: str) -> str:
    text = _CODE_BLOCK.sub(lambda m: f"\nBloque de código{' en ' + m.group(1) if m.group(1) else ''}.\n", text)
    lines, in_table = [], False
    for line in text.splitlines():
        if _TABLE_LINE.match(line):
            if not in_table:
                lines.append("Hay una tabla.")
            in_table = True
            continue
        in_table = False
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)  # títulos
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)  # viñetas
        line = re.sub(r"^\s*>\s?", "", line)  # citas
        lines.append(line)
    text = "\n".join(lines)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub(lambda m: f"un enlace a {m.group(1)}", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _PATH.sub(lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", text)  # negrita/cursiva
    text = text.replace("->", " a ").replace("→", " a ").replace("&", " y ")
    text = _strip_emoji(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


class Lexicon:
    def __init__(self, entries: dict[str, str]):
        self.rules = [
            (re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)", re.IGNORECASE), v)
            for k, v in sorted(entries.items(), key=lambda kv: -len(kv[0]))
        ]

    def __call__(self, text: str) -> str:
        for rx, rep in self.rules:
            # "El CI/CD" → "La integración…": conserva la mayúscula inicial
            # (solo si es "Título", no una SIGLA: "YAML" → "yámal")
            text = rx.sub(
                lambda m, r=rep: r[:1].upper() + r[1:]
                if m.group(0)[:1].isupper() and not m.group(0).isupper() else r,
                text,
            )
        return text


def sentences(text: str, max_len: int = 220) -> list[str]:
    """Trocea en frases (y agrupa las muy cortas) para empezar a hablar cuanto antes."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?…:;])\s+|\n+", text) if p.strip()]
    out: list[str] = []
    for p in parts:
        while len(p) > max_len:  # frase enorme: cortar por comas o espacios
            cut = p.rfind(",", 0, max_len)
            cut = cut if cut > 40 else p.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            out.append(p[: cut + 1].strip())
            p = p[cut + 1:].strip()
        if out and len(out[-1]) + len(p) < 60:
            out[-1] = f"{out[-1]} {p}"
        elif p:
            out.append(p)
    return out


def prepare(text: str, lexicon: Lexicon, max_chars: int = 4000) -> list[str]:
    text = text[:max_chars]
    # El lexicón va antes que el normalizador de rutas: "CI/CD" no debe leerse como ruta.
    return sentences(normalize(lexicon(text)))


# ---------------------------------------------------------------- hablar
class Speaker:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lexicon = Lexicon(cfg.get("lexicon") or {})
        self.tts = None
        self.ready = threading.Event()
        self.level = 0.0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stream = None

    def load(self):
        try:
            from ptts import TTS

            self.tts = TTS(model=self.cfg["model"], lang="es", quant=self.cfg["quant"], voice=self.cfg["voice"])
            list(self.tts.stream("Hola."))  # calentamiento
            log(f"[tts] phonon listo · voz {self.cfg['voice']}")
        except Exception as e:  # noqa: BLE001
            log(f"[tts] no disponible: {e}")
        finally:
            self.ready.set()

    @property
    def speaking(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self):
        self._stop.set()
        s = self._stream
        if s is not None:
            try:
                s.abort()
            except Exception:  # noqa: BLE001
                pass
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2)

    def say(self, text: str, on_start=None, on_end=None) -> bool:
        """Lee `text` en segundo plano (interrumpe lo que estuviera leyendo)."""
        with self._lock:
            self.stop()
            self.ready.wait()
            if self.tts is None:
                return False
            parts = prepare(text, self.lexicon, self.cfg.get("max_chars", 4000))
            if not parts:
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(parts, on_start, on_end), daemon=True)
            self._thread.start()
            return True

    def _run(self, parts, on_start, on_end):
        import sounddevice as sd

        try:
            with sd.OutputStream(samplerate=self.tts.sample_rate, channels=1, dtype="float32") as s:
                self._stream = s
                if on_start:
                    on_start(" ".join(parts))
                for part in parts:
                    if self._stop.is_set():
                        break
                    stream = self.tts.stream(part)
                    for chunk in stream:
                        if self._stop.is_set():
                            break
                        self.level = min(1.0, float(np.sqrt(np.mean(chunk**2))) * 12)
                        s.write(chunk.reshape(-1, 1))
                    del stream  # cerrar el generador detiene la síntesis
        except Exception as e:  # noqa: BLE001
            if not self._stop.is_set():
                log(f"[tts] error: {e}")
        finally:
            self._stream = None
            self.level = 0.0
            if on_end:
                on_end()
