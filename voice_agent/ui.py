"""Widget flotante minimalista (GTK4 + layer-shell).

Una "píldora" abajo al centro que nunca roba el foco:
  ● grabando  ▁▃▅▇▅  0:03
  ◌ transcribiendo…
  ✓ texto pegado
"""
from __future__ import annotations

import math
import time
from collections import deque

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

CSS = b"""
window.va { background: transparent; }
.pill {
  background: alpha(#141416, 0.92);
  border: 1px solid alpha(white, 0.08);
  border-radius: 999px;
  padding: 8px 16px 8px 12px;
  box-shadow: 0 6px 24px alpha(black, 0.35);
}
.pill label { color: #ececf1; font-family: "Inter", "Noto Sans", sans-serif; font-size: 13px; }
.pill .muted { color: alpha(#ececf1, 0.55); font-feature-settings: "tnum"; }
.pill .text { color: #ececf1; }
.dot { min-width: 10px; min-height: 10px; border-radius: 999px; background: #ff453a; }
.dot.busy { background: #0a84ff; }
.dot.ok { background: #30d158; }
.dot.err { background: #ff9f0a; }
"""

BARS = 22


class Pill:
    def __init__(self, app: Gtk.Application):
        self.win = Gtk.ApplicationWindow(application=app)
        self.win.add_css_class("va")
        self.win.set_decorated(False)
        self.win.set_resizable(False)

        LayerShell.init_for_window(self.win)
        LayerShell.set_namespace(self.win, "voice-agent")
        LayerShell.set_layer(self.win, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(self.win, LayerShell.Edge.BOTTOM, True)
        LayerShell.set_margin(self.win, LayerShell.Edge.BOTTOM, 48)
        LayerShell.set_keyboard_mode(self.win, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(self.win, -1)

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.win.get_display(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("pill")
        self.dot = Gtk.Box()
        self.dot.add_css_class("dot")
        self.dot.set_valign(Gtk.Align.CENTER)
        self.meter = Gtk.DrawingArea()
        self.meter.set_content_width(BARS * 4)
        self.meter.set_content_height(20)
        self.meter.set_draw_func(self._draw_meter)
        self.label = Gtk.Label(xalign=0)
        self.label.set_max_width_chars(48)
        self.label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        for w in (self.dot, self.meter, self.label):
            box.append(w)
        self.win.set_child(box)

        self.levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self.level_source = None  # callable → float
        self.t0 = 0.0
        self._tick_id = None
        self._hide_id = None
        self._phase = 0.0

    # --------------------------------------------------------------- dibujo
    def _draw_meter(self, area, cr, w, h):
        cr.set_source_rgba(0.93, 0.93, 0.95, 0.9)
        bw = w / BARS
        for i, lv in enumerate(self.levels):
            bh = max(2.0, lv * h)
            x = i * bw + bw * 0.2
            y = (h - bh) / 2
            r = min(bw * 0.3, bh / 2)
            cr.new_sub_path()
            cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            cr.arc(x + bw * 0.6 - r, y + r, r, 1.5 * math.pi, 0)
            cr.arc(x + bw * 0.6 - r, y + bh - r, r, 0, 0.5 * math.pi)
            cr.arc(x + r, y + bh - r, r, 0.5 * math.pi, math.pi)
            cr.close_path()
        cr.fill()

    def _tick(self):
        if self.level_source:
            lv = self.level_source()
            self.levels.append(lv ** 0.6)
            secs = int(time.monotonic() - self.t0)
            self.label.set_text(f"{secs // 60}:{secs % 60:02d}")
        else:  # animación "pensando"
            self._phase += 0.25
            for i in range(BARS):
                self.levels[i] = 0.15 + 0.35 * (1 + math.sin(self._phase - i * 0.45)) / 2
        self.meter.queue_draw()
        return True

    def _start_tick(self):
        if self._tick_id is None:
            self._tick_id = GLib.timeout_add(33, self._tick)

    def _stop_tick(self):
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None

    def _set_dot(self, kind: str):
        for c in ("busy", "ok", "err"):
            self.dot.remove_css_class(c)
        if kind:
            self.dot.add_css_class(kind)

    def _cancel_hide(self):
        if self._hide_id is not None:
            GLib.source_remove(self._hide_id)
            self._hide_id = None

    def _hide_later(self, ms: int):
        self._cancel_hide()

        def go():
            self._hide_id = None
            self.hide()
            return False

        self._hide_id = GLib.timeout_add(ms, go)

    # ------------------------------------------------------- estados (hilo UI)
    def recording(self, level_source):
        self._cancel_hide()
        self.level_source = level_source
        self.t0 = time.monotonic()
        self.levels.extend([0.0] * BARS)
        self._set_dot("")
        self.label.remove_css_class("text")
        self.label.add_css_class("muted")
        self.label.set_text("0:00")
        self.meter.set_visible(True)
        self._start_tick()
        self.win.set_visible(True)

    def busy(self, msg="transcribiendo"):
        self._cancel_hide()
        self.level_source = None
        self._set_dot("busy")
        self.label.set_text(msg)
        self.meter.set_visible(True)
        self._start_tick()
        self.win.set_visible(True)

    def done(self, text: str):
        self._stop_tick()
        self._set_dot("ok")
        self.meter.set_visible(False)
        self.label.remove_css_class("muted")
        self.label.add_css_class("text")
        self.label.set_text(text or "(nada)")
        self.win.set_visible(True)
        self._hide_later(1600)

    def error(self, msg: str):
        self._stop_tick()
        self._set_dot("err")
        self.meter.set_visible(False)
        self.label.set_text(msg)
        self.win.set_visible(True)
        self._hide_later(2500)

    def hide(self):
        self._stop_tick()
        self.level_source = None
        self.win.set_visible(False)
