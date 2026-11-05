"""Píldora Tkinter (Windows, X11, GNOME vía XWayland). Ventana sin bordes que no toma el foco."""
from __future__ import annotations

import queue
import sys
import tkinter as tk
import tkinter.font as tkfont

from .base import BARS, COLORS, PillModel

W, H = 300, 40
TRANSPARENT = "#010203"  # color clave para esquinas transparentes en Windows


class TkPill:
    def __init__(self):
        self.m = PillModel()
        self.q: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        bg = COLORS["bg"]
        if sys.platform == "win32":
            bg = TRANSPARENT
            self.root.attributes("-transparentcolor", TRANSPARENT)
        else:
            try:
                self.root.attributes("-alpha", 0.94)
            except tk.TclError:
                pass
        self.cv = tk.Canvas(self.root, width=W, height=H, bg=bg, highlightthickness=0, bd=0)
        self.cv.pack()
        self.font = tkfont.Font(family="Segoe UI" if sys.platform == "win32" else "Sans", size=10)
        self._hide_at = None
        self._hwnd = None

    # ------------------------------------------------------------ ventana
    def _place(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{sh - H - 90}")

    def _no_activate(self):
        """Windows: que la píldora nunca robe el foco a la ventana donde pegamos."""
        if sys.platform != "win32" or self._hwnd:
            return
        import ctypes

        u = ctypes.windll.user32
        self._hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = -20, 0x08000000, 0x80, 0x8
        style = u.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)

    def _show(self):
        self._place()
        if sys.platform == "win32":
            self.root.update_idletasks()
            self._no_activate()
            import ctypes

            ctypes.windll.user32.ShowWindow(self._hwnd, 4)  # SW_SHOWNOACTIVATE
        else:
            self.root.deiconify()
        self.root.lift()

    # ------------------------------------------------------------- dibujo
    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.cv.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        m, cv = self.m, self.cv
        cv.delete("all")
        self._round_rect(1, 1, W - 1, H - 1, H // 2, fill=COLORS["bg"], outline="#2a2a2e")
        cy = H // 2
        cv.create_oval(14, cy - 5, 24, cy + 5, fill=COLORS[m.dot], outline="")
        x = 36
        if m.show_meter:
            bw = 4
            for i, lv in enumerate(m.levels):
                bh = max(2, int(lv * 20))
                bx = x + i * bw
                cv.create_rectangle(bx, cy - bh / 2, bx + 2, cy + bh / 2, fill="#ededf2", outline="")
            x += BARS * bw + 10
        text = m.text
        maxw = W - x - 16
        while self.font.measure(text) > maxw and len(text) > 1:
            text = text[:-2] + "…"
        cv.create_text(x, cy, text=text, anchor="w", font=self.font,
                       fill=COLORS["muted"] if m.muted else COLORS["fg"])

    # -------------------------------------------------------------- bucle
    def _loop(self):
        while True:
            try:
                fn, a = self.q.get_nowait()
            except queue.Empty:
                break
            fn(*a)
        if self.m.animating:
            self.m.tick()
        if self.m.visible:
            self._draw()
        if self._hide_at is not None:
            self._hide_at -= 33
            if self._hide_at <= 0:
                self._hide_at = None
                self.hide()
        self.root.after(33, self._loop)

    def _apply(self, hide_after=None):
        self._hide_at = hide_after
        if self.m.visible:
            self._draw()
            self._show()
        else:
            self.root.withdraw()

    # -------------------------------------------------------------- API
    def call(self, fn, *a):
        self.q.put((fn, a))

    def recording(self, level_source):
        self.m.recording(level_source)
        self._apply()

    def busy(self, msg="transcribiendo"):
        self.m.busy(msg)
        self._apply()

    def done(self, text):
        self._apply(self.m.done(text))

    def error(self, msg):
        self._apply(self.m.error(msg))

    def hide(self):
        self.m.hide()
        self._apply()

    def run(self, on_ready):
        self.root.after(0, on_ready)
        self.root.after(33, self._loop)
        self.root.mainloop()
