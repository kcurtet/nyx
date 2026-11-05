"""jerga — dictado push-to-talk que entiende tu jerga técnica.

Uso:
  jerga                 arranca (widget + tecla global)
  jerga toggle|start|stop|cancel   controla el dictado de una instancia en marcha (atajos del escritorio)
  jerga say "texto"     lee el texto en voz alta (también por stdin: echo hola | jerga say)
  jerga say --brief …   solo las primeras frases + "el resto lo tienes en el panel"
  jerga read            lee el texto seleccionado (igual que Ctrl+;)
  jerga hush            calla
  jerga transcribe F…  audio/vídeo → .md con marcas de tiempo (--format srt|txt, --out DIR, --stdout)
  jerga record          graba una sesión larga y la va transcribiendo (--system: audio del PC, --both: micro + PC)
  jerga record stop     termina la sesión (y jerga record status)
  jerga look "pregunta" mira la pantalla con un modelo de visión local (--window: ventana activa, --all: todo)
  jerga trinity         arranca la orquestadora (pi en una pestaña de herdr)
  jerga order "texto"   manda una orden a Trinity (igual que decir «Trinity, …»)
  jerga doctor          comprueba que todo está listo en este equipo
  jerga keys            muestra el nombre de las teclas que pulses (para elegir la tecla)
  jerga config          muestra la ruta del archivo de configuración
  jerga tray            icono en la bandeja del sistema (lo arranca el servicio; [tray] enabled)
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
    state = {"recording": False, "busy": False, "error": ""}

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
        state["busy"] = True
        threading.Thread(target=process, args=(audio,), daemon=True).start()

    def process(audio):
        try:
            _process(audio)
        finally:
            state["busy"] = False

    def _process(audio):
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
        def status(_payload: str = "") -> str:
            import json

            return json.dumps({
                "version": __version__,
                "stt_ready": stt.model is not None,
                "stt_device": stt.device,
                "tts_ready": bool(speaker and speaker.tts is not None),
                "recording": state["recording"],
                "busy": state["busy"] or stt.lock.locked(),
                "speaking": bool(speaker and speaker.speaking),
                "dictation_key": cfg["hotkey"]["key"],
                "read_key": cfg["tts"]["key"],
                "orders": cfg["orders"]["agent"] if orch else None,
                "session": ({"path": str(session["s"].path), "elapsed": session["s"].elapsed,
                             "kind": session["s"].kind} if session["s"] else None),
            })

        # ------------------------------------------------- sesiones y notas de voz
        session = {"s": None}
        session_lock = threading.Lock()

        def notify(title: str, body: str = ""):
            import shutil
            import subprocess

            if config.IS_LINUX and shutil.which("notify-send"):
                subprocess.Popen(["notify-send", "-a", "jerga", "-i", "audio-input-microphone", title, body])

        def record_start(payload: str) -> str:
            import json
            from pathlib import Path

            from .session import Session, default_dir

            req = json.loads(payload or "{}")
            with session_lock:
                if session["s"]:
                    return json.dumps({"ok": False, "error": f"ya hay una sesión grabando en {session['s'].path}"})
                rc = cfg["record"]
                out = Path(req["out"]).expanduser() if req.get("out") else \
                    default_dir(rc) / time.strftime("sesion-%Y-%m-%d-%H%M.md")
                try:
                    s = Session(stt, post.apply_rules, req.get("mic", True), req.get("system", False), out,
                                labels=tuple(rc["labels"]), mic_device=rc["mic_device"])
                    s.start()
                except Exception as e:  # noqa: BLE001
                    return json.dumps({"ok": False, "error": str(e)})
                session["s"] = s
            notify("Grabando sesión", f"{s.kind} → {out}")
            return json.dumps({"ok": True, "path": str(out), "kind": s.kind})

        def record_stop(_payload: str = "") -> str:
            import json

            with session_lock:
                s, session["s"] = session["s"], None
            if s is None:
                return json.dumps({"ok": False, "error": "no hay ninguna sesión grabando"})
            path = s.stop()
            notify("Sesión guardada", f"{len(s.segments)} fragmentos → {path}")
            return json.dumps({"ok": True, "path": str(path), "segments": len(s.segments), "elapsed": s.elapsed})

        if cfg["notes"]["enabled"]:
            from .session import NotesWatcher, note_preview
            from .transcribe import transcribe_file

            def note_done(src, md):
                notify(f"Nota de voz: {src.name}", note_preview(md))

            NotesWatcher(cfg["notes"]["dirs"], cfg["notes"]["extensions"],
                         lambda p: transcribe_file(stt, post.apply_rules, p, opts=cfg["transcribe"])[0],
                         notify=note_done).start()

        def transcribe_req(payload: str) -> str:
            import json

            from .transcribe import run_request

            log(f"[transcribe] {payload[:200]}")
            res = run_request(stt, post.apply_rules, json.loads(payload))
            for line in res["log"]:
                log(f"[transcribe] {line}")
            return json.dumps(res, ensure_ascii=False)

        if cfg["tray"]["enabled"]:
            start_tray()

        ControlServer({"start": start, "stop": stop, "toggle": toggle, "cancel": cancel,
                       "say": say, "say-brief": lambda t: say(t, brief=True),
                       "read": read_selection, "hush": hush, "order": send_order,
                       "transcribe": transcribe_req, "status": status,
                       "record-start": record_start, "record-stop": record_stop,
                       "ping": lambda: None}).start()

    def start_tray():
        import subprocess

        from .platform_env import clean_child_env

        import importlib.util

        # Solo comprobar que existe: importarlo aquí cargaría GTK3 junto al GTK4 del widget.
        if importlib.util.find_spec("pystray") is None:
            log("[tray] sin icono de bandeja: instala pystray")
            return
        # Proceso aparte (GTK3 vs GTK4) y sin nuestro LD_PRELOAD; se cierra solo si el servicio cae.
        flags = {"creationflags": 0x08000000} if config.IS_WINDOWS else {}  # CREATE_NO_WINDOW
        subprocess.Popen([sys.executable, "-m", "jerga", "tray"], env=clean_child_env(), **flags)
        log("[tray] icono de bandeja en marcha")

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
    from pathlib import Path

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
    if cmd == "record":
        import json

        from .hotkey import send_command

        sub = args[1] if len(args) > 1 else ""
        try:
            if sub == "stop":
                res = json.loads(send_command("record-stop", timeout=None))
            elif sub == "status":
                st = json.loads(send_command("status")).get("session")
                print(f"grabando ({st['kind']}) desde hace {int(st['elapsed'])} s → {st['path']}" if st else "no hay sesión grabando")
                return
            else:
                flags = set(args[1:])
                req = {"mic": "--system" not in flags or "--both" in flags,
                       "system": "--system" in flags or "--both" in flags}
                if "--out" in args:
                    req["out"] = str(Path(args[args.index("--out") + 1]).expanduser().resolve())
                res = json.loads(send_command("record-start", json.dumps(req), timeout=30))
        except OSError:
            sys.exit("jerga no está en marcha")
        if not res.get("ok"):
            sys.exit(f"jerga record: {res.get('error')}")
        print(res["path"])
        return
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
    if cmd == "tray":  # ANTES de prepare(): sin LD_PRELOAD de GTK4 (AppIndicator usa GTK3)
        from .tray import main as tray_main

        sys.exit(tray_main())

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
