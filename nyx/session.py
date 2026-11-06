"""Sesiones largas en vivo (`nyx record`) y vigilante de notas de voz.

Sesión: micrófono y/o audio del sistema → trozos de ~25 s cortados en un silencio →
Whisper (el del servicio) → .md que se reescribe tras cada trozo (se puede abrir mientras
graba). Con dos fuentes, cada una se transcribe aparte: "Yo" (micro) / "Ellos" (sistema).

Notas de voz: vigila carpetas y transcribe los audios NUEVOS que aparezcan.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from .config import docs_root, log
from .platform_env import clean_child_env
from .transcribe import SR, Segment, decode, render, stamp, transcribe_audio

TARGET_S = 25.0  # tamaño buscado de cada trozo
MAX_S = 40.0  # corte forzado
SEARCH_S = 6.0  # buscar el silencio en los últimos N segundos del trozo
FRAME = int(SR * 0.1)


def quiet_cut(audio: np.ndarray, search_s: float = SEARCH_S) -> int:
    """Índice donde cortar: el tramo de 100 ms más silencioso de los últimos `search_s` s."""
    n = audio.size
    start = max(0, n - int(search_s * SR))
    tail = audio[start: n - (n - start) % FRAME] if n - start >= FRAME else audio[start:]
    if tail.size < FRAME:
        return n
    frames = tail.reshape(-1, FRAME)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    return start + int(np.argmin(rms)) * FRAME + FRAME // 2


class Chunker:
    """Acumula audio de una fuente y suelta trozos cortados en silencios."""

    def __init__(self, emit, speaker: str | None):
        self.emit = emit  # emit(audio, offset_s, speaker)
        self.speaker = speaker
        self.buf: list[np.ndarray] = []
        self.size = 0
        self.consumed = 0  # muestras ya emitidas (para la marca de tiempo)
        self.lock = threading.Lock()

    def feed(self, samples: np.ndarray) -> None:
        with self.lock:
            self.buf.append(samples)
            self.size += samples.size
            if self.size >= TARGET_S * SR:
                audio = np.concatenate(self.buf)
                cut = quiet_cut(audio) if audio.size < MAX_S * SR else quiet_cut(audio[: int(MAX_S * SR)])
                self._emit(audio[:cut])
                rest = audio[cut:]
                self.buf, self.size = [rest], rest.size

    def flush(self) -> None:
        with self.lock:
            if self.size:
                self._emit(np.concatenate(self.buf))
            self.buf, self.size = [], 0

    def _emit(self, audio: np.ndarray) -> None:
        offset = self.consumed / SR
        self.consumed += audio.size
        self.emit(audio, offset, self.speaker)


# ---------------------------------------------------------------- fuentes
class MicSource:
    def __init__(self, chunker: Chunker, device=None):
        import sounddevice as sd

        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=device,
                                     blocksize=int(SR * 0.1), callback=lambda d, *_: chunker.feed(d[:, 0].copy()))

    def start(self):
        self.stream.start()

    def stop(self):
        self.stream.stop()
        self.stream.close()


class SystemSource:
    """Lo que suena en el PC: monitor de la salida por defecto (PipeWire/PulseAudio vía parec)."""

    def __init__(self, chunker: Chunker):
        if not shutil.which("parec"):
            raise RuntimeError("para grabar el audio del sistema hace falta parec (pulseaudio-utils / pipewire-pulse)")
        self.chunker = chunker
        self.proc: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None

    def start(self):
        self.proc = subprocess.Popen(
            ["parec", "-d", "@DEFAULT_MONITOR@", "--format=s16le", f"--rate={SR}", "--channels=1", "--raw",
             "--latency-msec=100"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=clean_child_env())
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        block = int(SR * 0.1) * 2
        while self.proc and self.proc.poll() is None:
            data = self.proc.stdout.read(block)
            if not data:
                break
            self.chunker.feed(np.frombuffer(data, np.int16).astype(np.float32) / 32768)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.thread:
            self.thread.join(timeout=3)


# ---------------------------------------------------------------- sesión
def default_dir(cfg: dict) -> Path:
    if cfg.get("dir"):
        return Path(os.path.expanduser(cfg["dir"]))
    return docs_root() / "nyx"


class Session:
    def __init__(self, stt, fix, mic: bool, system: bool, path: Path, labels=("Yo", "Ellos"), mic_device=None,
                 on_update=None):
        if not (mic or system):
            raise ValueError("una sesión necesita micrófono, sistema o ambos")
        self.stt, self.fix, self.path = stt, fix, path
        self.started = time.time()
        self.segments: list[Segment] = []
        self.q: queue.Queue = queue.Queue()
        self.on_update = on_update
        both = mic and system
        self.sources = []
        self.chunkers = []
        if mic:
            c = Chunker(self._enqueue, labels[0] if both else None)
            self.chunkers.append(c)
            self.sources.append(MicSource(c, mic_device))
        if system:
            c = Chunker(self._enqueue, labels[1] if both else None)
            self.chunkers.append(c)
            self.sources.append(SystemSource(c))
        self.kind = "micrófono + sistema" if both else ("micrófono" if mic else "sistema")
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.title = f"Sesión {time.strftime('%Y-%m-%d %H:%M', time.localtime(self.started))} ({self.kind})"

    def _enqueue(self, audio, offset, speaker):
        self.q.put((audio, offset, speaker))

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write()
        self.worker.start()
        for s in self.sources:
            s.start()
        log(f"[sesión] grabando ({self.kind}) → {self.path}")

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    def stop(self) -> Path:
        for s in self.sources:
            s.stop()
        for c in self.chunkers:
            c.flush()
        self.q.put(None)
        self.worker.join()
        self._write(final=True)
        log(f"[sesión] terminada ({stamp(self.elapsed)}, {len(self.segments)} segmentos) → {self.path}")
        return self.path

    def _work(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            audio, offset, speaker = item
            try:
                segs = transcribe_audio(self.stt, audio, self.fix, offset, speaker)
            except Exception as e:  # noqa: BLE001
                log(f"[sesión] error transcribiendo un trozo: {e}")
                continue
            if segs:
                self.segments.extend(segs)
                self.segments.sort(key=lambda s: s.start)
                self._write()
                if self.on_update:
                    self.on_update(segs)

    def _write(self, final: bool = False):
        md = render(self.segments, "md", self.title, duration=self.elapsed)
        if not final:
            md += "\n*(grabando…)*\n"
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(md, encoding="utf-8")
        tmp.replace(self.path)


# ---------------------------------------------------------- notas de voz
class NotesWatcher(threading.Thread):
    """Transcribe los audios NUEVOS que aparezcan en las carpetas vigiladas (deja el .md al lado)."""

    def __init__(self, dirs: list[str], exts: list[str], transcribe_file, poll: float = 3.0, notify=None):
        super().__init__(daemon=True)
        self.dirs = [Path(os.path.expanduser(d)) for d in dirs]
        self.exts = {e.lower() for e in exts}
        self.transcribe_file = transcribe_file  # (Path) -> Path del .md
        self.poll = poll
        self.notify = notify
        self.seen: dict[Path, tuple[int, float]] = {}
        self.done: set[Path] = set()
        # Solo ficheros nuevos: los que ya estaban no se tocan. Margen de 2 s porque el reloj de
        # los ficheros puede ir unos ms por detrás de time.time() (pasa en Windows/NTFS).
        self.since = time.time() - 2.0
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def candidates(self) -> list[Path]:
        out = []
        for d in self.dirs:
            if not d.is_dir():
                continue
            for p in d.iterdir():
                if p.suffix.lower() in self.exts and p.is_file() and p not in self.done:
                    out.append(p)
        return out

    def step(self) -> list[Path]:
        """Una pasada: devuelve los .md creados. Un fichero se procesa cuando lleva un ciclo sin cambiar."""
        made = []
        for p in self.candidates():
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < self.since or p.with_suffix(".md").exists():
                self.done.add(p)
                continue
            sig = (st.st_size, st.st_mtime)
            if self.seen.get(p) != sig:  # aún descargándose
                self.seen[p] = sig
                continue
            self.done.add(p)
            try:
                md = self.transcribe_file(p)
                made.append(md)
                log(f"[notas] {p.name} → {md.name}")
                if self.notify:
                    self.notify(p, md)
            except Exception as e:  # noqa: BLE001
                log(f"[notas] error con {p.name}: {e}")
        return made

    def run(self):
        log(f"[notas] vigilando {', '.join(map(str, self.dirs))} ({', '.join(sorted(self.exts))})")
        while not self._stop.wait(self.poll):
            self.step()


def notes_dirs(notes_cfg: dict, record_cfg: dict) -> list[str]:
    """Carpetas vigiladas: las configuradas o, si no hay, ~/Documentos/nyx/notas (creada)."""
    if notes_cfg.get("dirs"):
        return list(notes_cfg["dirs"])
    d = default_dir(record_cfg) / "notas"
    d.mkdir(parents=True, exist_ok=True)
    return [str(d)]


def note_preview(md_path: Path, n: int = 160) -> str:
    """Primer texto de una transcripción .md para la notificación."""
    for line in md_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("`["):
            text = line.split("` ", 1)[-1]
            return text if len(text) <= n else text[: n - 1] + "…"
    return ""


__all__ = ["Chunker", "NotesWatcher", "Session", "default_dir", "note_preview", "quiet_cut", "decode"]
