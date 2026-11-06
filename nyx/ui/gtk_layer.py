"""Píldora GTK4 + layer-shell (Wayland: KDE, Sway, Hyprland…). Nunca roba el foco."""
from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from .base import BARS, COLORS, PillModel  # noqa: E402

CSS = f"""
window.jerga {{ background: transparent; }}
.pill {{
  background: alpha({COLORS['bg']}, 0.92);
  border: 1px solid alpha(white, 0.08);
  border-radius: 999px;
  padding: 8px 16px 8px 12px;
}}
.pill label {{ color: {COLORS['fg']}; font-size: 13px; }}
.pill label.muted {{ color: alpha({COLORS['fg']}, 0.55); font-feature-settings: "tnum"; }}
.dot {{ min-width: 10px; min-height: 10px; border-radius: 999px; background: {COLORS['rec']}; }}
.dot.busy {{ background: {COLORS['busy']}; }}
.dot.ok {{ background: {COLORS['ok']}; }}
.dot.err {{ background: {COLORS['err']}; }}
.dot.speak {{ background: {COLORS['speak']}; }}
""".encode()


class GtkPill:
    def __init__(self):
        self.m = PillModel()
        self.app = Gtk.Application(application_id="io.github.kcurtet.jerga")
        self.win = None
        self._tick_id = self._hide_id = None

    # ------------------------------------------------------------ montaje
    def _build(self, app):
        win = Gtk.ApplicationWindow(application=app)
        win.add_css_class("jerga")
        win.set_decorated(False)
        win.set_resizable(False)
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "jerga")
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(win, LayerShell.Edge.BOTTOM, True)
        LayerShell.set_margin(win, LayerShell.Edge.BOTTOM, 48)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(win, -1)

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(win.get_display(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("pill")
        self.dot = Gtk.Box()
        self.dot.add_css_class("dot")
        self.dot.set_valign(Gtk.Align.CENTER)
        self.meter = Gtk.DrawingArea()
        self.meter.set_content_width(BARS * 4)
        self.meter.set_content_height(20)
        self.meter.set_draw_func(self._draw)
        self.label = Gtk.Label(xalign=0)
        self.label.set_max_width_chars(48)
        self.label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        for w in (self.dot, self.meter, self.label):
            box.append(w)
        win.set_child(box)
        self.win = win

    def _draw(self, area, cr, w, h):
        cr.set_source_rgba(0.93, 0.93, 0.95, 0.9)
        bw = w / BARS
        for i, lv in enumerate(self.m.levels):
            bh = max(2.0, lv * h)
            x, y, r = i * bw + bw * 0.2, (h - bh) / 2, min(bw * 0.3, bh / 2)
            cr.new_sub_path()
            cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            cr.arc(x + bw * 0.6 - r, y + r, r, 1.5 * math.pi, 0)
            cr.arc(x + bw * 0.6 - r, y + bh - r, r, 0, 0.5 * math.pi)
            cr.arc(x + r, y + bh - r, r, 0.5 * math.pi, math.pi)
            cr.close_path()
        cr.fill()

    # ------------------------------------------------------------ render
    def _render(self, hide_after=None):
        m = self.m
        for c in ("busy", "ok", "err", "speak"):
            self.dot.remove_css_class(c)
        if m.dot != "rec":
            self.dot.add_css_class(m.dot)
        (self.label.add_css_class if m.muted else self.label.remove_css_class)("muted")
        self.label.set_text(m.text)
        self.meter.set_visible(m.show_meter)
        self.meter.queue_draw()
        if m.animating and self._tick_id is None:
            self._tick_id = GLib.timeout_add(33, self._tick)
        self._cancel_hide()
        if hide_after:
            self._hide_id = GLib.timeout_add(hide_after, self._auto_hide)
        self.win.set_visible(m.visible)

    def _tick(self):
        if not self.m.animating:
            self._tick_id = None
            return False
        self.m.tick()
        self.label.set_text(self.m.text)
        self.meter.queue_draw()
        return True

    def _cancel_hide(self):
        if self._hide_id is not None:
            GLib.source_remove(self._hide_id)
            self._hide_id = None

    def _auto_hide(self):
        self._hide_id = None
        self.hide()
        return False

    # -------------------------------------------- API (llamar en hilo UI)
    def call(self, fn, *a):
        GLib.idle_add(lambda: (fn(*a), False)[1])

    def recording(self, level_source):
        self.m.recording(level_source)
        self._render()

    def busy(self, msg="transcribiendo"):
        self.m.busy(msg)
        self._render()

    def speaking(self, level_source, text):
        self.m.speaking(level_source, text)
        self._render()

    def done(self, text):
        self._render(self.m.done(text))

    def error(self, msg):
        self._render(self.m.error(msg))

    def hide(self):
        self.m.hide()
        self._render()

    def run(self, on_ready):
        def activate(app):
            if self.win is None:
                self._build(app)
                app.hold()  # seguir vivo con la ventana oculta
                on_ready()

        self.app.connect("activate", activate)
        self.app.run([])
