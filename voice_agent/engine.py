"""Audio → texto → texto corregido → salida en el cursor."""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time

import numpy as np


# ---------------------------------------------------------------- grabación
class Recorder:
    def __init__(self, samplerate: int = 16000, device=None):
        import sounddevice as sd

        self.sd = sd
        self.sr = samplerate
        self.device = device
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self.level = 0.0  # RMS del último bloque (0..1 aprox), para la UI
        self.started_at = 0.0

    def _cb(self, indata, frames, t, status):
        self._chunks.append(indata[:, 0].copy())
        rms = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
        self.level = min(1.0, rms * 12)

    def start(self):
        self._chunks = []
        self.level = 0.0
        self._stream = self.sd.InputStream(
            samplerate=self.sr, channels=1, dtype="float32",
            device=self.device, blocksize=int(self.sr * 0.03), callback=self._cb,
        )
        self._stream.start()
        self.started_at = time.monotonic()

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.level = 0.0
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._chunks)


# ---------------------------------------------------------------------- STT
class Transcriber:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = None
        self.ready = threading.Event()

    def load(self):
        from faster_whisper import WhisperModel

        c = self.cfg
        self.model = WhisperModel(c["model"], device=c["device"], compute_type=c["compute_type"])
        # calentamiento: la primera inferencia compila kernels CUDA
        list(self.model.transcribe(np.zeros(16000, dtype=np.float32), language=c["language"])[0])
        self.ready.set()

    def prompt(self) -> str:
        vocab = self.cfg.get("vocabulary") or []
        if not vocab:
            return ""
        # Un texto de ejemplo "estilo programador hispano" condiciona mejor que una lista suelta.
        return "Notas de desarrollo, mezclando español e inglés técnico: " + ", ".join(vocab) + "."

    def transcribe(self, audio: np.ndarray) -> str:
        self.ready.wait()
        c = self.cfg
        segs, _ = self.model.transcribe(
            audio,
            language=c["language"],
            beam_size=c["beam_size"],
            initial_prompt=self.prompt() or None,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segs).strip()


# ------------------------------------------------------------ post-proceso
class PostProcessor:
    def __init__(self, replacements: dict, llm: dict, vocabulary: list[str]):
        # Ordenamos por longitud para que "docker con pose" gane a "docker".
        self.rules = [
            (re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)", re.IGNORECASE), v)
            for k, v in sorted(replacements.items(), key=lambda kv: -len(kv[0]))
        ]
        self.llm = llm
        self.vocab = vocabulary

    def apply_rules(self, text: str) -> str:
        # varias pasadas: "dóquer con pose" → "Docker con pose" → "docker compose"
        for _ in range(3):
            before = text
            for rx, rep in self.rules:
                text = rx.sub(rep, text)
            if text == before:
                break
        return text

    def apply_llm(self, text: str) -> str:
        if not self.llm.get("enabled") or not text:
            return text
        import httpx

        system = (
            "Corriges transcripciones de voz de un programador que habla español y mezcla "
            "términos técnicos en inglés. Corrige SOLO palabras técnicas mal transcritas "
            "(p. ej. 'guit pus' -> 'git push', 'dóquer' -> 'Docker'). No traduzcas, no reformules, "
            "no añadas ni quites nada más, mantén la puntuación. Responde únicamente con el texto corregido.\n"
            "Glosario: " + ", ".join(self.vocab)
        )
        try:
            r = httpx.post(
                self.llm["url"].rstrip("/") + "/api/chat",
                json={
                    "model": self.llm["model"],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                },
                timeout=self.llm.get("timeout", 4.0),
            )
            r.raise_for_status()
            out = r.json()["message"]["content"].strip().strip('"').strip()
            # salvaguarda: si el LLM se enrolla, nos quedamos con el original
            if not out or len(out) > len(text) * 1.5 + 20:
                return text
            return out
        except Exception as e:  # noqa: BLE001
            print(f"[llm] fallo, uso texto sin corregir: {e}")
            return text

    def __call__(self, text: str) -> str:
        return self.apply_llm(self.apply_rules(text))


# ------------------------------------------------------------------ salida
# keycodes de linux/input-event-codes.h
KEYCODES = {
    "shift": 42, "ctrl": 29, "alt": 56, "super": 125,
    "insert": 110, "v": 47, "enter": 28,
}


class Output:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.env = dict(os.environ)
        self.env.setdefault("YDOTOOL_SOCKET", f"/run/user/{os.getuid()}/.ydotool_socket")

    def finalize(self, text: str) -> str:
        if self.cfg["strip_final_period"] and text.endswith(".") and not text.endswith(".."):
            text = text[:-1]
        if self.cfg["trailing_space"] and text:
            text += " "
        return text

    def _ydotool_combo(self, combo: str):
        codes = [KEYCODES[k.strip().lower()] for k in combo.split("+")]
        seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
        subprocess.run(["ydotool", "key", *seq], env=self.env, check=False)

    def _get_clip(self, primary=False) -> bytes | None:
        try:
            args = ["wl-paste", "--no-newline"] + (["--primary"] if primary else [])
            r = subprocess.run(args, capture_output=True, timeout=1)
            return r.stdout if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    def _set_clip(self, data: bytes, primary=False):
        args = ["wl-copy"] + (["--primary"] if primary else [])
        subprocess.run(args, input=data, check=False)

    def emit(self, text: str):
        if not text:
            return
        method = self.cfg["method"]
        if method == "type":
            subprocess.run(["ydotool", "type", "--", text], env=self.env, check=False)
            return
        old = old_p = None
        if method == "paste" and self.cfg["restore_clipboard"]:
            old, old_p = self._get_clip(), self._get_clip(primary=True)
        data = text.encode()
        # Clipboard + primary: así shift+insert funciona tanto en apps como en terminales.
        self._set_clip(data)
        self._set_clip(data, primary=True)
        if method == "clipboard":
            return
        time.sleep(0.05)
        self._ydotool_combo(self.cfg["paste_keys"])
        if self.cfg["restore_clipboard"]:
            def restore():
                time.sleep(0.6)
                if old is not None:
                    self._set_clip(old)
                if old_p is not None:
                    self._set_clip(old_p, primary=True)
            threading.Thread(target=restore, daemon=True).start()
