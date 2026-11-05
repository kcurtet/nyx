"""Orquestación: hotkey → grabar → transcribir → corregir → pegar, con el widget."""
from __future__ import annotations

import sys
import threading
import time

from . import config
from .engine import Output, PostProcessor, Recorder, Transcriber
from .hotkey import ControlSocket, HotkeyListener, send_command


def run():
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    from .ui import Pill

    cfg = config.load()
    rec = Recorder(cfg["audio"]["samplerate"], cfg["audio"]["device"])
    stt = Transcriber(cfg["stt"])
    post = PostProcessor(cfg["replacements"], cfg["llm"], cfg["stt"]["vocabulary"])
    out = Output(cfg["output"])
    lock = threading.Lock()
    state = {"recording": False}

    app = Gtk.Application(application_id="dev.kx.VoiceAgent")
    ui: dict = {}

    def on_ui(fn, *a):
        GLib.idle_add(lambda: (fn(*a), False)[1])

    def start():
        with lock:
            if state["recording"]:
                return
            try:
                rec.start()
            except Exception as e:  # noqa: BLE001
                on_ui(ui["pill"].error, f"micrófono: {e}")
                return
            state["recording"] = True
        on_ui(ui["pill"].recording, lambda: rec.level)

    def cancel():
        with lock:
            if not state["recording"]:
                return
            state["recording"] = False
            rec.stop()
        on_ui(ui["pill"].hide)

    def stop():
        with lock:
            if not state["recording"]:
                return
            state["recording"] = False
            dur = time.monotonic() - rec.started_at
            audio = rec.stop()
        if dur < cfg["hotkey"]["min_seconds"]:
            on_ui(ui["pill"].hide)
            return
        on_ui(ui["pill"].busy, "transcribiendo" if stt.ready.is_set() else "cargando modelo…")
        threading.Thread(target=process, args=(audio,), daemon=True).start()

    def process(audio):
        try:
            t0 = time.monotonic()
            raw = stt.transcribe(audio)
            t1 = time.monotonic()
            text = post(raw)
            t2 = time.monotonic()
            print(f"[stt {t1 - t0:.2f}s] {raw!r}")
            if text != raw:
                print(f"[fix {t2 - t1:.2f}s] {text!r}")
            if not text:
                on_ui(ui["pill"].error, "no se ha oído nada")
                return
            out.emit(out.finalize(text))
            on_ui(ui["pill"].done, text)
        except Exception as e:  # noqa: BLE001
            print("[error]", repr(e))
            on_ui(ui["pill"].error, str(e)[:60])

    def toggle():
        (stop if state["recording"] else start)()

    def load_model():
        try:
            stt.load()
            print("[stt] modelo listo")
            on_ui(ui["pill"].done, "listo para dictar")
        except Exception as e:  # noqa: BLE001
            print("[stt] error cargando modelo:", repr(e))
            on_ui(ui["pill"].error, f"modelo: {e}"[:60])

    def activate(_app):
        if "pill" in ui:
            return
        ui["pill"] = Pill(_app)
        ui["pill"].busy("cargando modelo…")
        _app.hold()  # seguir vivo con la ventana oculta
        threading.Thread(target=load_model, daemon=True).start()
        HotkeyListener(cfg["hotkey"]["key"], cfg["hotkey"]["mode"], start, stop, cancel).start()
        ControlSocket({"start": start, "stop": stop, "toggle": toggle, "cancel": cancel}).start()

    app.connect("activate", activate)
    app.run([])


def main():
    args = sys.argv[1:]
    if args and args[0] in ("start", "stop", "toggle", "cancel"):
        try:
            print(send_command(args[0]))
        except OSError:
            print("voice-agent no está corriendo", file=sys.stderr)
            sys.exit(1)
        return
    if args and args[0] == "keys":
        # Ayuda para elegir tecla: imprime el nombre de lo que pulses.
        import evdev
        from evdev import ecodes

        devs = [evdev.InputDevice(p) for p in evdev.list_devices()]
        devs = [d for d in devs if ecodes.EV_KEY in d.capabilities() and "ydotool" not in d.name]
        print("Pulsa teclas (Ctrl+C para salir)…")
        import selectors

        sel = selectors.DefaultSelector()
        for d in devs:
            sel.register(d, selectors.EVENT_READ)
        while True:
            for k, _ in sel.select():
                for ev in k.fileobj.read():
                    if ev.type == ecodes.EV_KEY and ev.value == 1:
                        print(ecodes.KEY.get(ev.code, ev.code))
    run()
