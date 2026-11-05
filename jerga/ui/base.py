"""Estado y animación compartidos por todos los widgets."""
from __future__ import annotations

import math
import threading
import time
from collections import deque

from ..config import log

BARS = 22

COLORS = {
    "bg": "#141416",
    "fg": "#ececf1",
    "muted": "#8a8a90",
    "rec": "#ff453a",
    "busy": "#0a84ff",
    "ok": "#30d158",
    "err": "#ff9f0a",
}


class PillModel:
    """Lo que hay que dibujar: punto, barras y texto. El backend pinta y programa ticks."""

    def __init__(self):
        self.levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self.level_source = None
        self.dot = "rec"
        self.text = ""
        self.muted = True
        self.show_meter = True
        self.visible = False
        self.animating = False
        self.t0 = 0.0
        self._phase = 0.0

    def tick(self):
        if self.level_source:
            self.levels.append(self.level_source() ** 0.6)
            secs = int(time.monotonic() - self.t0)
            self.text = f"{secs // 60}:{secs % 60:02d}"
        else:  # ola "pensando"
            self._phase += 0.25
            for i in range(BARS):
                self.levels[i] = 0.15 + 0.35 * (1 + math.sin(self._phase - i * 0.45)) / 2

    # Transiciones. Devuelven ms tras los que ocultar (o None).
    def recording(self, level_source):
        self.level_source, self.t0 = level_source, time.monotonic()
        self.levels.extend([0.0] * BARS)
        self.dot, self.text, self.muted, self.show_meter = "rec", "0:00", True, True
        self.visible = self.animating = True

    def busy(self, msg):
        self.level_source = None
        self.dot, self.text, self.muted, self.show_meter = "busy", msg, True, True
        self.visible = self.animating = True

    def done(self, text):
        self.level_source = None
        self.dot, self.text, self.muted, self.show_meter = "ok", text or "(nada)", False, False
        self.visible, self.animating = True, False
        return 1600

    def error(self, msg):
        self.level_source = None
        self.dot, self.text, self.muted, self.show_meter = "err", msg, False, False
        self.visible, self.animating = True, False
        return 2500

    def hide(self):
        self.level_source = None
        self.visible = self.animating = False


class HeadlessUI:
    """Sin ventana: mismas llamadas, solo log."""

    def call(self, fn, *a):
        fn(*a)

    def recording(self, level_source):
        log("● grabando")

    def busy(self, msg="transcribiendo"):
        log(f"… {msg}")

    def done(self, text):
        pass

    def error(self, msg):
        log(f"⚠ {msg}")

    def hide(self):
        pass

    def run(self, on_ready):
        on_ready()
        threading.Event().wait()
