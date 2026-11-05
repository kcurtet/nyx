"""jerga — dictado push-to-talk que entiende tu jerga técnica.

Uso:
  jerga                 arranca (widget + tecla global)
  jerga toggle|start|stop|cancel   controla el dictado de una instancia en marcha (atajos del escritorio)
  jerga say "texto"     lee el texto en voz alta (también por stdin: echo hola | jerga say)
  jerga say --brief …   solo las primeras frases + "el resto lo tienes en el panel"
  jerga read            lee el texto seleccionado (igual que Ctrl+;)
  jerga hush            calla
  jerga transcribe F…  audio/vídeo → .md con marcas de tiempo (--format srt|txt, --out DIR, --stdout)
  jerga look "pregunta" mira la pantalla con un modelo de visión local (--window: ventana activa, --all: todo)
  jerga trinity         arranca la orquestadora (pi en una pestaña de herdr)
  jerga order "texto"   manda una orden a Trinity (igual que decir «Trinity, …»)
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
    from .orders import Orchestrator, match_wake
    from .tts import Speaker

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
    speaker = Speaker(cfg["tts"]) if cfg["tts"]["enabled"] else None
    orch = Orchestrator(cfg["orders"]) if cfg["orders"]["enabled"] else None
    lock = threading.Lock()
    state = {"recording": False}

    def start():
        if speaker and speaker.speaking:  # si empiezas a hablar, se calla
            speaker.stop()
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
            log(f"[stt {t1 - t0:.2f}s] {raw!r}")
            if orch is not None:
                order = match_wake(post.apply_rules(raw), cfg["orders"]["wake_words"])
                if order is not None:
                    send_order(order)
                    return
            res = post.process(raw)
            text = res.text
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

    # ------------------------------------------------------------- órdenes
    def send_order(order: str):
        name = cfg["orders"]["agent"]
        if orch is None:
            log("[orden] desactivado en la config ([orders] enabled = false)")
            return
        order = order.strip()
        if not order:
            ui.call(ui.done, f"{name}: ¿sí?")
            say("Dime.")
            return
        log(f"[orden → {name}] {order!r}")
        ok, msg = orch.send(order)
        if ok:
            ui.call(ui.done, f"→ {name}: {order}")
        else:
            ui.call(ui.error, msg)
            say(msg)

    # ------------------------------------------------------------- leer en voz alta
    def say(text: str, brief: bool = False):
        if speaker is None:
            log("[tts] desactivado en la config ([tts] enabled = false)")
            return
        text = (text or "").strip()
        if not text:
            ui.call(ui.error, "nada que leer")
            return
        if not speaker.ready.is_set():
            ui.call(ui.busy, "cargando voz…")
        log(f"[tts] leyendo {len(text)} caracteres")

        from .tts import normalize

        shown = " ".join(normalize(text).split())  # el original, no la versión fonética
        shown = shown if len(shown) <= 60 else shown[:57] + "…"
        ok = speaker.say(
            text,
            brief=brief,
            on_start=lambda _spoken: ui.call(ui.speaking, lambda: speaker.level, shown),
            on_end=lambda: ui.call(ui.hide),
        )
        if not ok:
            ui.call(ui.error, "no se pudo leer (mira el log)")

    def hush():
        if speaker and speaker.speaking:
            speaker.stop()
            ui.call(ui.hide)

    def read_selection():
        if speaker and speaker.speaking:  # segunda pulsación: callar
            hush()
            return
        say(out.selection())

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
        combos = []
        if speaker:
            threading.Thread(target=speaker.load, daemon=True).start()
            combos.append((cfg["tts"]["key"], read_selection))
        ptt = PushToTalk(cfg["hotkey"]["mode"], start, stop, cancel)
        try:
            make_listener(cfg["hotkey"]["key"], ptt, combos).start()
        except Exception as e:  # noqa: BLE001
            log(f"[hotkey] no disponible ({e}); usa `jerga toggle` desde un atajo del escritorio")
        def transcribe_req(payload: str) -> str:
            import json

            from .transcribe import run_request

            log(f"[transcribe] {payload[:200]}")
            res = run_request(stt, post.apply_rules, json.loads(payload))
            for line in res["log"]:
                log(f"[transcribe] {line}")
            return json.dumps(res, ensure_ascii=False)

        ControlServer({"start": start, "stop": stop, "toggle": toggle, "cancel": cancel,
                       "say": say, "say-brief": lambda t: say(t, brief=True),
                       "read": read_selection, "hush": hush, "order": send_order,
                       "transcribe": transcribe_req,
                       "ping": lambda: None}).start()

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
    if cmd == "look":
        from .vision import main as look_main

        sys.exit(look_main(args[1:], config.load()["vision"]))
    if cmd == "trinity":
        from .orders import launch

        sys.exit(launch(config.load()["orders"]))
    if cmd in ("start", "stop", "toggle", "cancel", "read", "hush", "say", "order"):
        from .hotkey import send_command

        payload = ""
        if cmd in ("say", "order"):
            rest = args[1:]
            if cmd == "say" and rest[:1] == ["--brief"]:  # resumen hablado: corta por frases
                cmd, rest = "say-brief", rest[1:]
            payload = " ".join(rest) if rest else ("" if sys.stdin.isatty() else sys.stdin.read())
            if not payload.strip():
                sys.exit(f'uso: jerga {cmd} "texto"   o   echo "texto" | jerga {cmd}')
        try:
            print(send_command(cmd, payload))
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
    if cmd == "transcribe":
        from .transcribe import main as transcribe_main

        sys.exit(transcribe_main(args[1:], config.load()))
    if cmd == "doctor":
        from .doctor import doctor

        sys.exit(doctor())
    if cmd == "run":
        run()
        return
    sys.exit(f"comando desconocido: {cmd}\n{__doc__}")
