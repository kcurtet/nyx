"""Whisper (faster-whisper) con vocabulario técnico en el prompt."""
from __future__ import annotations

import gc
import threading
from collections.abc import Callable

import numpy as np

from .config import log


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


class Transcriber:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = None
        self.device = None
        self.ready = threading.Event()
        self.error: Exception | None = None
        self.lock = threading.Lock()  # dictado, transcripciones, load y unload comparten el modelo
        self._priority = 0  # dictados esperando el modelo: las transcripciones largas ceden el turno
        self._prio_lock = threading.Lock()
        self.on_loaded: Callable[[], None] | None = None  # avisa de toda recarga exitosa (spec 006 D4b)
        self._loading = threading.Lock()  # guard atómico (acquire no bloqueante): una sola carga en marcha

    def _load(self, device: str):
        from faster_whisper import WhisperModel

        ct = self.cfg["compute_type"]
        if ct == "auto":
            ct = "float16" if device == "cuda" else "int8"
        model = WhisperModel(self.cfg["model"], device=device, compute_type=ct)
        # calentamiento: la primera inferencia carga cuBLAS/cuDNN y compila kernels
        list(model.transcribe(np.zeros(16000, dtype=np.float32), language=self.cfg["language"])[0])
        self.model, self.device = model, device
        log(f"[stt] modelo {self.cfg['model']} listo en {device} ({ct})")

    def load(self):
        """Carga el modelo con la llave TOMADA DURANTE TODA la carga: serializa con unload()
        (un toggle a GPU libre espera a que acabe y luego descarga; nunca queda modelo con el
        modo libre) y con la inferencia. Guard ATÓMICO: `acquire(blocking=False)` es
        check-and-set de una pieza (el patrón is_set()+set() dejaba pasar N hilos a la vez);
        early-return si el modelo ya está o si alguien ya está cargando."""
        if self.model is not None:
            return
        if not self._loading.acquire(blocking=False):  # alguien ya carga: return inmediato
            return
        self.ready.clear()  # carga nueva en marcha: el veredicto anterior (éxito o fallo) caduca
        try:
            want = self.cfg["device"]
            device = ("cuda" if cuda_available() else "cpu") if want == "auto" else want
            try:
                with self.lock:
                    try:
                        self._load(device)
                    except Exception as e:  # noqa: BLE001
                        if device != "cuda" or want == "cuda":
                            raise
                        log(f"[stt] CUDA falló ({e}); uso CPU. Instala el extra [cuda] para usar la GPU.")
                        self._load("cpu")
                    self.error = None  # una carga con éxito borra el error de la anterior
                if self.on_loaded:
                    self.on_loaded()
            except Exception as e:  # noqa: BLE001
                self.error = e
                raise
            finally:
                self.ready.set()
        finally:
            self._loading.release()

    def unload(self):
        """Modo GPU libre: suelta el modelo de memoria. Bajo llave (recheck TOCTOU): espera a que
        acaben cargas e inferencias en curso; idempotente. El servicio y la config siguen vivos."""
        with self.lock:
            if self.model is None:
                return
            self.model = None
            self.device = None
            self.error = None
            self.ready.clear()
        gc.collect()
        log(f"[stt] modelo {self.cfg['model']} descargado (GPU libre)")

    def _spawn_load(self):
        def go():
            try:
                self.load()
            except Exception:  # noqa: BLE001  # queda en self.error: lo ven los que esperan
                pass

        threading.Thread(target=go, daemon=True).start()

    def _ensure_loaded(self):
        """Espera al modelo; si falta y nadie está cargando (modo GPU libre), lo recarga solo.
        Self-healing de spec 006 D2: nadie se queda colgado en ready.wait() sin carga en marcha."""
        while self.model is None and self.error is None:
            if not self._loading.locked():
                self._spawn_load()
            self.ready.wait()
        if self.model is None:
            raise RuntimeError(f"modelo no disponible: {self.error}")

    def prompt(self) -> str:
        vocab = self.cfg.get("vocabulary") or []
        if not vocab:
            return ""
        # Un texto "estilo programador hispano" condiciona mejor que una lista suelta.
        return "Notas de desarrollo, mezclando español e inglés técnico: " + ", ".join(vocab) + "."

    @property
    def dictation_waiting(self) -> bool:
        return self._priority > 0

    def segments(self, audio: np.ndarray, context: str = ""):
        """Audio largo (ficheros, sesiones): segmentos con tiempos y contexto entre ellos.
        `context`: final del bloque anterior, para no perder el hilo entre bloques.
        Recheck del modelo DENTRO de la llave: un unload() que gane la llave en el hueco tras
        _ensure_loaded() se reintenta (bucle) SIN la llave tomada — nunca None.transcribe."""
        prompt = " ".join(p for p in (self.prompt(), context.strip()) if p)
        while True:
            self._ensure_loaded()
            with self.lock:
                if self.model is None:  # unload() ganó la llave en el hueco: salir y reintentar
                    continue  # (nunca _ensure_loaded() con la llave tomada: su load() la necesita)
                segs, _ = self.model.transcribe(
                    audio,
                    language=self.cfg["language"],
                    beam_size=self.cfg["beam_size"],
                    initial_prompt=prompt or None,
                    vad_filter=True,
                    condition_on_previous_text=True,  # coherencia en textos largos
                )
                return list(segs)

    def transcribe(self, audio: np.ndarray) -> str:
        """Recheck del modelo DENTRO de la llave (igual que segments): un unload() que gane la
        llave en el hueco tras _ensure_loaded() se reintenta en bucle SIN la llave tomada."""
        while True:
            self._ensure_loaded()
            with self._prio_lock:
                self._priority += 1  # el dictado pasa delante de los bloques de transcripciones largas
            try:
                with self.lock:
                    if self.model is None:  # unload() ganó la llave en el hueco: salir y reintentar
                        continue  # (el continue suelta la llave ANTES de volver a _ensure_loaded)
                    segs, _ = self.model.transcribe(
                        audio,
                        language=self.cfg["language"],
                        beam_size=self.cfg["beam_size"],
                        initial_prompt=self.prompt() or None,
                        vad_filter=True,
                        condition_on_previous_text=False,
                    )
                    return " ".join(s.text.strip() for s in segs).strip()
            finally:
                with self._prio_lock:
                    self._priority -= 1
