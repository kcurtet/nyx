"""jerga — dictado push-to-talk que entiende tu jerga técnica.

Uso:
  jerga                 arranca (widget + tecla global)
  jerga toggle|start|stop|cancel   controla una instancia en marcha (para atajos del escritorio)
  jerga doctor          comprueba que todo está listo en este equipo
  jerga keys            muestra el nombre de las teclas que pulses (para elegir la tecla)
  jerga config          muestra la ruta del archivo de configuración
"""
from __future__ import annotations

import signal
import sys
import threading
import time

from . import __version__, config
from .config import log


def run():
    from . import ui as ui_mod
    from .audio import Recorder
    from .hotkey import ControlServer, PushToTalk, is_running, make_listener
    from .output import Output
    from .postprocess import PostProcessor
    from .stt import Transcriber

    if is_running():
        print("jerga ya está en marcha. Usa `jerga toggle` o ciérralo primero.")
        sys.exit(1)

    cfg = config.load()
    log(f"jerga {__version__} · config: {config.CONFIG_PATH}")
    rec = Recorder(cfg["audio"]["samplerate"], cfg["audio"]["device"])
    stt = Transcriber(cfg["stt"])
    post = PostProcessor(cfg["replacements"], cfg["llm"], cfg["stt"]["vocabulary"], cfg["commands"])
    out = Output(cfg["output"])
    ui = ui_mod.create(cfg["ui"]["backend"])
    lock = threading.Lock()
    state = {"recording": False}

    def start():
        with lock:
            if state["recording"]:
                return
            try:
                rec.start()
            except Exception as e:  # noqa: BLE001
                ui.call(ui.error, f"micrófono: {e}"[:60])
                return
            state["recording"] = True
        ui.call(ui.recording, lambda: rec.level)

    def cancel():
        with lock:
            if not state["recording"]:
                return
            state["recording"] = False
            rec.stop()
        ui.call(ui.hide)

    def stop():
        with lock:
            if not state["recording"]:
                return
            state["recording"] = False
            dur = time.monotonic() - rec.started_at
            audio = rec.stop()
        if dur < cfg["hotkey"]["min_seconds"]:
            ui.call(ui.hide)
            return
        ui.call(ui.busy, "transcribiendo" if stt.ready.is_set() else "cargando modelo…")
        threading.Thread(target=process, args=(audio,), daemon=True).start()

    def process(audio):
        try:
            t0 = time.monotonic()
            raw = stt.transcribe(audio)
            t1 = time.monotonic()
            res = post.process(raw)
            text = res.text
            log(f"[stt {t1 - t0:.2f}s] {raw!r}")
            if text != raw or res.send or res.discard:
                flags = (" [envía]" if res.send else "") + (" [descartado]" if res.discard else "")
                log(f"[fix {time.monotonic() - t1:.2f}s] {text!r}{flags}")
            if res.discard:
                ui.call(ui.done, "descartado")
                return
            if not text:
                ui.call(ui.error, "no se ha oído nada")
                return
            out.emit(out.finalize(text, res.send))
            if res.send:
                out.press_enter()
            ui.call(ui.done, text + ("  ⏎" if res.send else ""))
        except Exception as e:  # noqa: BLE001
            log("[error]", repr(e))
            ui.call(ui.error, str(e)[:60])

    def toggle():
        (stop if state["recording"] else start)()

    def load_model():
        try:
            stt.load()
            ui.call(ui.done, "listo para dictar")
        except Exception as e:  # noqa: BLE001
            log("[stt] error cargando modelo:", repr(e))
            ui.call(ui.error, f"modelo: {e}"[:60])

    def on_ready():
        ui.busy("cargando modelo…")
        threading.Thread(target=load_model, daemon=True).start()
        ptt = PushToTalk(cfg["hotkey"]["mode"], start, stop, cancel)
        try:
            make_listener(cfg["hotkey"]["key"], ptt).start()
        except Exception as e:  # noqa: BLE001
            log(f"[hotkey] no disponible ({e}); usa `jerga toggle` desde un atajo del escritorio")
        ControlServer({"start": start, "stop": stop, "toggle": toggle,
                       "cancel": cancel, "ping": lambda: None}).start()

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    ui.run(on_ready)


def keys():
    if config.IS_WINDOWS:
        from pynput import keyboard

        print("Pulsa teclas (Ctrl+C para salir)…")
        with keyboard.Listener(on_press=lambda k: print(k)) as lst:
            lst.join()
        return
    import selectors

    import evdev
    from evdev import ecodes

    sel = selectors.DefaultSelector()
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
        except OSError:
            continue
        if ecodes.EV_KEY in d.capabilities() and "jerga" not in d.name and "ydotool" not in d.name:
            sel.register(d, selectors.EVENT_READ)
    if not sel.get_map():
        sys.exit("No puedo leer ningún teclado: añade tu usuario al grupo `input` y vuelve a iniciar sesión.")
    print("Pulsa teclas (Ctrl+C para salir)…")
    while True:
        for k, _ in sel.select():
            for ev in k.fileobj.read():
                if ev.type == ecodes.EV_KEY and ev.value == 1:
                    name = ecodes.KEY.get(ev.code, ev.code)
                    print(name[0] if isinstance(name, list) else name)


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return
    if cmd in ("-V", "--version", "version"):
        print(__version__)
        return
    if cmd in ("start", "stop", "toggle", "cancel"):
        from .hotkey import send_command

        try:
            print(send_command(cmd))
        except OSError:
            sys.exit("jerga no está en marcha")
        return
    if cmd == "config":
        print(config.ensure_config())
        return
    if cmd == "keys":
        keys()
        return

    from .platform_env import prepare

    prepare()  # puede re-ejecutar el proceso con el entorno CUDA/GTK correcto
    if cmd == "doctor":
        from .doctor import doctor

        sys.exit(doctor())
    if cmd == "run":
        run()
        return
    sys.exit(f"comando desconocido: {cmd}\n{__doc__}")
