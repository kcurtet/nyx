"""nyx — dictado push-to-talk que entiende tu jerga técnica.

     \\
     (o>
    //\\

Uso:
  nyx                  arranca (widget + tecla global)
  nyx toggle|start|stop|cancel   controla el dictado de una instancia en marcha (atajos del escritorio)
  nyx say "texto"     lee el texto en voz alta (también por stdin: echo hola | nyx say)
  nyx say --brief …   solo las primeras frases + "el resto lo tienes en el panel"
  nyx read            lee el texto seleccionado (igual que Ctrl+;)
  nyx hush            calla
  nyx transcribe F…  audio/vídeo → .md con marcas de tiempo (--format srt|txt, --out DIR, --stdout)
  nyx record          graba una sesión larga y la va transcribiendo (--system: audio del PC, --both: micro + PC)
  nyx record stop     termina la sesión (y nyx record status)
  nyx look "pregunta" mira la pantalla con un modelo de visión local (--window: ventana activa, --all: todo)
  nyx launch "nombre"  abre una app o juego instalado (--list para ver los nombres)
  nyx vol [up|down|mute|N]  volumen del sistema (±10 %, mute conmuta, N fija el porcentaje)
  nyx remind "texto" en <cuándo>  recordatorio one-shot (20m, 1h, 18:00; --list, --cancel N)
  nyx agent [restart]  arranca la orquestadora (herdr si está; si no, pi en segundo plano)
                     ("nyx trinity" sigue valiendo como alias silencioso)
  nyx order "texto"   manda una orden a Nyx (igual que decir «Nyx, …»)
  nyx doctor          comprueba que todo está listo en este equipo
  nyx keys            muestra el nombre de las teclas que pulses (para elegir la tecla)
  nyx config          muestra la ruta del archivo de configuración
  nyx tray            icono en la bandeja del sistema (lo arranca el servicio; [tray] enabled)

El alias `jerga` (nombre anterior) sigue funcionando y te lo recuerda una sola vez.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

from . import __version__, config
from .config import log


def run():
    from . import ui as ui_mod
    from .audio import Recorder
    from .hotkey import ControlServer, PushToTalk, is_running, make_listener
    from .orders import Orchestrator, match_wake
    from .output import Output
    from .postprocess import PostProcessor
    from .stt import Transcriber
    from .tts import Speaker

    if is_running():
        print("nyx ya está en marcha. Usa `nyx toggle` o ciérralo primero.")
        sys.exit(1)

    cfg = config.load()
    log(f"nyx {__version__} · config: {config.CONFIG_PATH}")
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
            if res.action:
                log(f"[orden local] {res.action} ← {raw!r}")
                ui.call(ui.hide)
                (read_selection if res.action == "read" else hush)()
                return
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
        say(out.selection(cfg["tts"].get("selection", "copy")))

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
            make_listener(cfg["hotkey"]["key"], ptt, combos, cfg["hotkey"].get("ctrl_keys")).start()
        except Exception as e:  # noqa: BLE001
            log(f"[hotkey] no disponible ({e}); usa `nyx toggle` desde un atajo del escritorio")
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
                "nyx": ({"backend": orch.kind, "state": orch.status(max_age=5), "reason": orch.reason}
                        if orch else None),
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
                subprocess.Popen(["notify-send", "-a", "nyx", "-i", "audio-input-microphone", title, body])

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
            from .session import NotesWatcher, note_preview, notes_dirs
            from .transcribe import transcribe_file

            def note_done(src, md):
                notify(f"Nota de voz: {src.name}", note_preview(md))

            NotesWatcher(notes_dirs(cfg["notes"], cfg["record"]), cfg["notes"]["extensions"],
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
        if orch and cfg["orders"].get("autostart", True):
            orch.start_supervisor()

        def agent_start(_payload: str = "") -> str:
            if orch is None:
                return "Las órdenes están desactivadas ([orders] enabled = false)."
            return orch.launch()[1]

        def agent_restart(_payload: str = "") -> str:
            if orch is None:
                return "Las órdenes están desactivadas ([orders] enabled = false)."
            if orch.kind == "pi":
                orch.stop()
            elif orch.kind == "herdr":
                from .orders import _herdr

                code, data, _ = _herdr("agent", "get", orch.agent)
                ws = ((data or {}).get("result", {}).get("agent") or {}).get("workspace_id")
                if ws:
                    _herdr("workspace", "close", ws)
            return orch.launch()[1]

        ControlServer({"start": start, "stop": stop, "toggle": toggle, "cancel": cancel,
                       "say": say, "say-brief": lambda t: say(t, brief=True),
                       "read": read_selection, "hush": hush, "order": send_order,
                       "transcribe": transcribe_req, "status": status,
                       "record-start": record_start, "record-stop": record_stop,
                       "agent-start": agent_start, "agent-restart": agent_restart,
                       "ping": lambda: None}).start()

    def start_tray():
        import importlib.util
        import subprocess

        from .platform_env import clean_child_env

        # Solo comprobar que existe: importarlo aquí cargaría GTK3 junto al GTK4 del widget.
        if importlib.util.find_spec("pystray") is None:
            log("[tray] sin icono de bandeja: instala pystray")
            return
        # Proceso aparte (GTK3 vs GTK4) y sin nuestro LD_PRELOAD; se cierra solo si el servicio cae.
        flags = {"creationflags": 0x08000000} if config.IS_WINDOWS else {}  # CREATE_NO_WINDOW
        subprocess.Popen([sys.executable, "-m", "nyx", "tray"], env=clean_child_env(), **flags)
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

    from .output import teclado_simulado

    sel = selectors.DefaultSelector()
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
        except OSError:
            continue
        if ecodes.EV_KEY in d.capabilities() and not teclado_simulado(d.name):
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


def _utf8_console() -> None:
    """La consola de Windows usa cp1252 por defecto: sin esto, ✔/✘/· rompen `nyx doctor`."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if stream is not None and enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _aviso_alias() -> None:
    """`jerga` es un alias de transición de `nyx` (spec 003, D3): una línea por stderr, UNA sola vez.

    Se detecta por argv[0] (el symlink ~/.local/bin/jerga) o porque el wrapper de Windows
    (jerga.cmd) exporta NYX_ALIAS=jerga. El marker vive en STATE_DIR: si no se puede escribir,
    se avisa igual (y se reintentará la próxima vez)."""
    invocado = Path(sys.argv[0]).name.lower() if sys.argv[0] else ""
    if "jerga" not in invocado and os.environ.get("NYX_ALIAS", "").lower() != "jerga":
        return
    marker = config.STATE_DIR / ".alias-avisado"
    if marker.exists():
        return
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass
    print("jerga ahora es nyx", file=sys.stderr)


def main():
    _utf8_console()
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return
    if cmd in ("-V", "--version", "version"):
        print(__version__)
        return
    from . import migrate

    for msg in migrate.run():  # rutas viejas de jerga → nyx, antes de tocar la config
        log("[migración]", msg)
    # El aviso va DESPUÉS de migrar: su marker crea STATE_DIR y antes lo creaba vacío,
    # con lo que la migración veía «conviven» y el estado viejo no se movía nunca (review 003).
    _aviso_alias()
    if cmd == "look":
        from .vision import main as look_main

        sys.exit(look_main(args[1:], config.load()["vision"]))
    if cmd == "launch":  # ANTES de prepare(): resolver y lanzar sin el LD de CUDA de nyx
        from .launch import main as launch_main

        sys.exit(launch_main(args[1:]))
    if cmd == "vol":  # ANTES de prepare(): pactl no necesita el LD de CUDA de nyx
        from .vol import main as vol_main

        sys.exit(vol_main(args[1:]))
    if cmd == "remind":  # ANTES de prepare(): systemd-run no necesita el LD de CUDA de nyx
        from .remind import main as remind_main

        sys.exit(remind_main(args[1:]))
    if cmd in ("agent", "trinity"):  # "trinity": alias silencioso una versión (spec 003, D4)
        from .hotkey import is_running, send_command

        sub = "agent-restart" if args[1:2] == ["restart"] else "agent-start"
        if is_running():  # el servicio la gestiona (también sin herdr, en segundo plano)
            print(send_command(sub, timeout=120))
            return
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
            sys.exit("nyx no está en marcha")
        if not res.get("ok"):
            sys.exit(f"nyx record: {res.get('error')}")
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
                sys.exit(f'uso: nyx {cmd} "texto"   o   echo "texto" | nyx {cmd}')
        try:
            print(send_command(cmd, payload))
        except OSError:
            sys.exit("nyx no está en marcha")
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
