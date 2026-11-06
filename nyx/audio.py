"""Grabación del micrófono."""
from __future__ import annotations

import time

import numpy as np


class Recorder:
    def __init__(self, samplerate: int = 16000, device=None):
        import sounddevice as sd

        self.sd = sd
        self.sr = samplerate
        self.device = device
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self.level = 0.0  # RMS del último bloque (0..1 aprox), para el widget
        self.started_at = 0.0

    def _cb(self, indata, frames, t, status):
        mono = indata[:, 0].copy()
        self._chunks.append(mono)
        self.level = min(1.0, float(np.sqrt(np.mean(mono**2))) * 12)

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
