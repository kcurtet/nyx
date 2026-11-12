"""Órdenes por voz: "Nyx, …" va a la orquestadora (una sesión de pi) en vez de pegarse.

Tres formas de tenerla (backend):
  herdr:   en su propio workspace de herdr — ves lo que hace y puede vigilar a tus agentes
           (pi-herdr en modo global).
  pi:      sin herdr — pi en segundo plano (`pi --mode rpc`) gestionado por el servicio de nyx.
           Mismas capacidades salvo los paneles y los agentes de herdr.
  efimero: nada encendido — cada orden arranca un `pi -p` one-shot (misma sesión en fichero,
           --continue), la respuesta se lee en voz alta desde el servicio y pi muere.
auto (por defecto): herdr si está instalado (nyx arranca su servidor si hace falta);
si no puede, pi; sin pi → no disponible.

El servicio la arranca solo y la vuelve a levantar si se cae (Supervisor; con efimero no
hay nada residente que levantar).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import date
from pathlib import Path

from .commands import _fold
from .config import STATE_DIR, log
from .platform_env import clean_child_env

AGENT_DIR = Path(__file__).resolve().parent / "nyx"


def match_wake(text: str, wake_words: list[str]) -> str | None:
    """Si `text` empieza por una palabra de activación, devuelve la orden (sin ella); si no, None.

    "Nyx, ve al repo nyx." → "Ve al repo nyx."   ·   "Nyx." → ""
    """
    folded = _fold(text)
    for w in sorted(wake_words, key=len, reverse=True):
        m = re.match(r"[\s¿¡\"'«]*(?:oye,?\s+)?" + re.escape(_fold(w)) + r"(?=$|[\s,.:;!?])[\s,.:;!?]*", folded)
        if m:
            rest = text[m.end():].strip()
            return rest[:1].upper() + rest[1:]
    return None


def _herdr(*args: str, timeout: float = 10) -> tuple[int, dict | None, str]:
    exe = shutil.which("herdr")
    if not exe:
        return 127, None, "herdr no está instalado"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, env=clean_child_env())
    except subprocess.TimeoutExpired:
        return 124, None, "herdr no responde"
    out = (r.stdout or "") + (r.stderr or "")
    try:
        data = json.loads(r.stdout) if r.stdout.strip().startswith("{") else None
    except json.JSONDecodeError:
        data = None
    rcode = r.returncode
    if data and "error" in data:
        rcode = 1  # herdr 0.9.3: rc 0 con cuerpo {"error":…} es un fallo encubierto (D4); data se conserva
    return rcode, data, out.strip()


def _pi_agent_dir() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")


def _pi_herdr_path(cfg: dict) -> Path:
    """Ruta de pi-herdr: la configurada en [orders] pi_herdr o la instalación por defecto
    de `pi install github:kcurtet/pi-herdr` (doctor y la orquestadora comparten esta ruta)."""
    p = cfg.get("pi_herdr")
    return Path(os.path.expanduser(p)) if p else _pi_agent_dir() / "git" / "github.com" / "kcurtet" / "pi-herdr"


def _ext_file(path: Path) -> Path | None:
    """Ruta cargable con -e: el propio fichero, la extensión declarada en el package.json
    del paquete ("pi": {"extensions": [...]}) o su index.ts/js."""
    if path.is_file():
        return path
    pkg = path / "package.json"
    if pkg.is_file():
        try:
            for rel in (json.loads(pkg.read_text()).get("pi") or {}).get("extensions") or []:
                found = _ext_file((path / rel).resolve())
                if found:
                    return found
        except (ValueError, OSError):
            pass
    for name in ("index.ts", "index.js"):
        if (path / name).is_file():
            return path / name
    return None


def find_pi_package(name: str) -> Path | None:
    """Un paquete instalado con `pi install` (npm o git), por nombre; o una ruta."""
    p = Path(os.path.expanduser(name))
    if p.exists():
        return _ext_file(p)
    base = _pi_agent_dir()
    for cand in [base / "npm" / "node_modules" / name, *sorted((base / "git").glob(f"*/*/{name}"))]:
        ext = _ext_file(cand)
        if ext:
            return ext
    return None


def pi_args_for(cfg: dict, with_herdr: bool = True, voice: bool = True) -> list[str]:
    """Argumentos de pi para la orquestadora.

    isolated (por defecto): sin extensiones ni skills del usuario (nada de formularios
    interactivos que no se pueden contestar por voz, menos contexto), solo:
    [integración de estado de herdr + pi-herdr (modo global)] + su voz.
    voice=False (backend efímero): sin voice.ts — la respuesta la lee el propio backend
    (on_say); cargada, habría doble voz.
    """
    args = ["--skill", str(AGENT_DIR)]
    if cfg.get("isolated", True):
        args = ["--no-extensions", "--no-skills", *args]
        if with_herdr:
            state = _pi_agent_dir() / "extensions" / "herdr-agent-state.ts"
            if state.is_file():
                args += ["-e", str(state)]
            herdr_pkg = _pi_herdr_path(cfg)
            ext = _ext_file(herdr_pkg)
            if ext:
                args += ["-e", str(ext)]
            else:
                log(f"[orden] pi-herdr no encontrado en {herdr_pkg}: sin herdr_watch")
        # Extensiones extra (p.ej. pi-web-access para buscar en internet): solo si están instaladas.
        for name in cfg.get("extensions") or []:
            ext = find_pi_package(name)
            if ext:
                args += ["-e", str(ext)]
            else:
                log(f"[orden] extensión '{name}' no instalada (pi install npm:{name}); se omite")
    args += ["-e", str(AGENT_DIR / "voice.ts")] if voice else []
    if cfg.get("model"):
        args += ["--model", cfg["model"]]
    return args


def _herdr_server_running() -> bool:
    """True solo si `herdr status --json` dice que el SERVER corre (D1: `herdr status` sale rc 0
    aunque esté parado). rc != 0, excepción o timeout → False. Con rc 0 y stdout no-JSON
    (herdr viejo sin --json), fallback textual: `status: running` bajo la sección server."""
    code, data, out = _herdr("status", "--json", timeout=2)
    if code != 0:
        return False
    server = (data or {}).get("server") if isinstance(data, dict) else None
    if isinstance(server, dict) and server.get("running") is True:
        return True
    en_server = False
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("server:"):
            en_server = True
        elif not line[0].isspace():  # otra sección de primer nivel
            en_server = False
        elif en_server and line.strip() == "status: running":
            return True
    return False


def herdr_available() -> bool:
    return shutil.which("herdr") is not None and _herdr_server_running()


_SERVER_STARTED_BY_NYX = False  # True si el último arranque del server lo hizo nyx (lo cuenta doctor, D5)


def _ensure_herdr_server(timeout: float = 8.0) -> tuple[bool, str]:
    """Arranca `herdr server` headless si hace falta y espera (deadline wall-clock) a que responda.

    (True, "") si el servidor acaba running; (False, motivo) si no. Cada sondeo es
    `_herdr_server_running()` (status --json, timeout propio de 2 s): un herdr colgado no
    puede estirar el plazo. Si otro proceso gana la carrera y el nuestro muere con
    "already running", el bucle lo absorbe: verá running y no habrá duplicados.
    """
    global _SERVER_STARTED_BY_NYX
    if _herdr_server_running():
        return True, ""
    exe = shutil.which("herdr")
    if not exe:
        return False, "herdr no está instalado"
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_DIR / "herdr-server.log", "ab") as logf:  # append: sobrevive a reinicios (D6)
            subprocess.Popen([exe, "server"], stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                             env=clean_child_env(), start_new_session=os.name == "posix")
    except OSError as e:
        return False, f"no pude lanzar herdr server: {e}"
    _SERVER_STARTED_BY_NYX = True
    log(f"[orden] herdr server lanzado por nyx (log: {STATE_DIR / 'herdr-server.log'})")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _herdr_server_running():
            return True, ""
        time.sleep(0.25)
    return False, "herdr server no responde tras arrancarlo"


def choose_backend(cfg: dict) -> tuple[str | None, str]:
    """(backend, motivo). backend None = no disponible; el motivo se dice en voz alta.

    pi primero (HerdrBackend ejecuta pi como agente): sin pi no se toca herdr.
    want="herdr": arranca el servidor y sin él, error claro — SIN caer a pi.
    want="auto": herdr instalado → arranca el servidor; si no puede, pi en segundo plano.
    Sin memoizar fallos: el supervisor reintenta en su próximo ciclo.
    """
    want = cfg.get("backend", "auto")
    if not shutil.which("pi"):
        return None, "Nyx no está disponible: falta pi. Instálalo para poder darme órdenes."
    if want == "efimero":
        return "efimero", ""  # sin proceso residente: las órdenes la arrancan
    if want == "herdr":
        if not shutil.which("herdr"):
            return None, "Nyx está configurada con herdr, pero herdr no está instalado."
        ok, why = _ensure_herdr_server()
        if not ok:
            return None, f"Nyx no está disponible: no he podido arrancar herdr ({why})."
        return "herdr", ""
    if want == "auto" and shutil.which("herdr"):
        ok, _ = _ensure_herdr_server()
        return ("herdr", "") if ok else ("pi", "")
    return "pi", ""


# ------------------------------------------------------------------ herdr
class HerdrBackend:
    name = "herdr"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.agent = cfg["agent"]
        self.title = self.agent[:1].upper() + self.agent[1:]

    def status(self) -> str | None:
        """Estado del agente (idle/working/blocked…) o None si no existe."""
        code, data, _ = _herdr("agent", "get", self.agent)
        if code != 0 or not data:
            return None
        return (data.get("result", {}).get("agent") or {}).get("agent_status", "unknown")

    def send(self, order: str) -> tuple[bool, str]:
        st = self.status()
        if st is None:
            return False, f"No encuentro a {self.title}. La estoy arrancando, repítemelo en un momento."
        if st == "blocked":
            return False, f"{self.title} está esperando una aprobación en su panel."
        # --wait --until working: confirma que el agente arranca el turno. Si el texto se queda
        # escrito sin enviar (pi aún arrancando, un aviso en pantalla…), pulsamos Enter y comprobamos.
        code, _, out = _herdr("agent", "prompt", self.agent, order, "--wait", "--until", "working",
                              "--until", "blocked", "--until", "done", "--timeout", "8000", timeout=15)
        if code == 0:
            return True, ""
        if "stalled" in out or "timeout" in out.lower():
            log(f"[orden] el turno no arrancó ({out[:120]}); pulso Enter")
            _herdr("agent", "send-keys", self.agent, "enter")
            code, _, out = _herdr("agent", "wait", self.agent, "--until", "working", "--until", "done",
                                  "--timeout", "6000", timeout=10)
            if code == 0:
                return True, ""
        log(f"[orden] herdr falló: {out[:200]}")
        return False, f"No he podido mandar la orden a {self.title}. Mira su panel."

    def _orphans(self) -> list[str]:
        """Workspaces/pestañas con su nombre pero sin agente registrado (herdr perdió el registro)."""
        code, data, _ = _herdr("workspace", "list")
        if code != 0 or not data:
            return []
        return [w["workspace_id"] for w in data.get("result", {}).get("workspaces", [])
                if w.get("label") == self.agent]

    def launch(self) -> tuple[bool, str]:
        if self.status() is not None:
            return True, f"{self.title} ya está en marcha (herdr agent focus {self.agent} para verla)."
        for ws in self._orphans():  # restos de una sesión anterior: fuera, para no tener dos
            log(f"[orden] cierro el workspace huérfano {ws}")
            _herdr("workspace", "close", ws)
        # PI_HERDR_SCOPE=global: pi-herdr ve y vigila TODOS los agentes de herdr (spec 004 de pi-herdr)
        extra = ["--env", "PI_HERDR_SCOPE=global"] + (["--env", "NYX_VOICE_DEBUG=1"] if self.cfg.get("debug") else [])
        where = "workspace" if self.cfg.get("topology", "workspace") == "workspace" else "tab"
        code, data, out = _herdr(where, "create", "--label", self.agent, "--cwd", str(Path.home()),
                                 "--no-focus", *extra)
        pane = ((data or {}).get("result", {}).get("root_pane") or {}).get("pane_id")
        if code != 0 or not pane:
            return False, f"No pude crear el {where}: {out[:300]}"
        pi_args = [*pi_args_for(self.cfg), "--name", self.agent]
        code, _, out = _herdr("agent", "start", self.agent, "--kind", "pi", "--pane", pane, "--", *pi_args, timeout=60)
        if code != 0:
            return False, f"No pude arrancar pi: {out[:300]}"
        # No darla por buena hasta que pi esté de verdad esperando órdenes.
        _herdr("agent", "wait", self.agent, "--until", "idle", "--timeout", "60000", timeout=65)
        return True, f"{self.title} en marcha en su {where} '{self.agent}'. Dile: «{self.title}, …»"

    def stop(self) -> None:
        pass  # su workspace sigue siendo tuyo: no lo cerramos al parar nyx


# --------------------------------------------------------------- pi (RPC)
class PiRpcBackend:
    """pi en segundo plano (`pi --mode rpc`), dentro del servicio. Conserva la conversación
    entre reinicios (--session-dir + --continue). La voz la pone la misma extensión voice.ts."""

    name = "pi"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.agent = cfg["agent"]
        self.title = self.agent[:1].upper() + self.agent[1:]
        self.proc: subprocess.Popen | None = None
        self.busy = False
        self.lock = threading.Lock()
        self.sessions = STATE_DIR / f"{self.agent}-sessions"

    def status(self) -> str | None:
        if self.proc is None or self.proc.poll() is not None:
            return None
        return "working" if self.busy else "idle"

    def launch(self) -> tuple[bool, str]:
        with self.lock:
            if self.status() is not None:
                return True, f"{self.title} ya está en marcha (en segundo plano)."
            self.sessions.mkdir(parents=True, exist_ok=True)
            env = clean_child_env()
            if self.cfg.get("debug"):
                env["NYX_VOICE_DEBUG"] = "1"
            args = ["pi", "--mode", "rpc", "--session-dir", str(self.sessions), "--continue",
                    *pi_args_for(self.cfg, with_herdr=False)]
            errlog = open(STATE_DIR / f"{self.agent}-pi.log", "ab")
            try:
                self.proc = subprocess.Popen(args, cwd=Path.home(), env=env, text=True, bufsize=1,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog)
            except OSError as e:
                return False, f"No pude arrancar pi: {e}"
            threading.Thread(target=self._read_events, daemon=True).start()
            log(f"[orden] {self.title} en marcha en segundo plano (pi --mode rpc, sin herdr)")
            return True, f"{self.title} en marcha en segundo plano. Dile: «{self.title}, …»"

    def _read_events(self) -> None:
        proc = self.proc
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "agent_start":
                self.busy = True
            elif kind == "agent_end":
                self.busy = False
            elif kind == "response" and not ev.get("success", True):
                log(f"[orden] pi rechazó {ev.get('command')}: {str(ev.get('error'))[:200]}")
        self.busy = False

    def send(self, order: str) -> tuple[bool, str]:
        if self.status() is None:
            return False, f"{self.title} no está en marcha. La estoy arrancando, repítemelo en un momento."
        # Si está trabajando, la orden entra como continuación al acabar (no la interrumpe).
        cmd = {"type": "follow_up" if self.busy else "prompt", "message": order}
        try:
            self.proc.stdin.write(json.dumps(cmd, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as e:
            return False, f"No he podido mandar la orden a {self.title}: {e}"
        self.busy = True
        return True, ""

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ------------------------------------------------------------ pi efímero
class EfimeroBackend:
    """pi solo mientras trabaja: cada orden arranca un `pi -p` one-shot con la memoria en
    fichero (mismo --session-dir + --continue que el backend pi), lee la respuesta en voz
    alta (on_say, brief) y muere. Nada residente: "idle" = en reposo (disponible), no caído.

    La voz la pone el propio backend (pi_args_for voice=False): sin voice.ts habría doble
    lectura. cwd pinneado a Path.home(): pi agrupa las sesiones por cwd y sin pinneo la
    memoria puede romperse entre reinicios del servicio. La respuesta de `pi -p` llega
    completa en stdout; exit != 0 con texto parcial (stop length) también se lee.
    """

    name = "efimero"
    MSG_ERROR = "No he podido ejecutar la orden."

    def __init__(self, cfg: dict, on_say=None):
        self.cfg = cfg
        self.agent = cfg["agent"]
        self.title = self.agent[:1].upper() + self.agent[1:]
        self.on_say = on_say  # (texto, brief=…) — la voz del servicio; los otros backends la ignoran
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.sessions = STATE_DIR / f"{self.agent}-sessions"
        self.stopping = False  # stop() del servicio: el lector no debe dar voz de error
        self.fresh_next = False  # «Sesión nueva»: el próximo arranque va sin --continue

    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def status(self) -> str | None:
        return "working" if self._alive() else "idle"  # NUNCA None: no hay nada que lanzar

    def launch(self) -> tuple[bool, str]:
        return True, f"{self.title} lista; las órdenes la arrancan. Dile: «{self.title}, …»"

    def _newest_is_today(self) -> bool:
        """True si la sesión más reciente del directorio es de HOY. Sin ficheros, también True:
        no hay memoria de ayer que cortar (y `--continue` con directorio vacío arranca sesión
        nueva, continueRecent de pi). False → toca rotar: spawn fresco sin --continue."""
        try:
            newest = max(p.stat().st_mtime for p in self.sessions.glob("*.jsonl"))
        except ValueError:  # sin sesiones todavía
            return True
        return newest >= time.mktime(date.today().timetuple())  # medianoche local

    def new_session(self) -> str:
        """«Sesión nueva» (tray): el próximo arranque no arrastra la conversación."""
        with self.lock:
            if self._alive():
                return f"{self.title} está trabajando, espera a que termine."
            self.fresh_next = True
        self._say("Sesión nueva.")
        return ""

    def send(self, order: str) -> tuple[bool, str]:
        with self.lock:
            if self._alive():
                return False, f"{self.title} está ocupada, espera a que termine."
            self.sessions.mkdir(parents=True, exist_ok=True)
            fresh = self.fresh_next or not self._newest_is_today()  # rotación: pedida o diaria
            # Opciones ANTES de «--»: para pi, todo lo que sigue a «--» es posicional (la orden)
            # — así las órdenes que empiecen por «-» no se comen las opciones. Spawn fresco =
            # SOLO omitir --continue (nada de borrar ficheros: pi decide qué resume).
            args = ["pi", "-p", "--session-dir", str(self.sessions)]
            if not fresh:
                args.append("--continue")
            args += [*pi_args_for(self.cfg, with_herdr=False, voice=False), "--", order]
            errlog = open(STATE_DIR / f"{self.agent}-pi.log", "ab")
            try:
                self.proc = subprocess.Popen(args, cwd=Path.home(), env=clean_child_env(), text=True,
                                             stdout=subprocess.PIPE, stderr=errlog)
            except OSError as e:
                errlog.close()
                return False, f"No he podido arrancar pi: {e}"
            if fresh:
                self.fresh_next = False  # consumido por este spawn
            log(f"[orden] {self.title} trabajando (pi -p one-shot{', sesión nueva' if fresh else ''})")
        threading.Thread(target=self._read_answer, args=(self.proc, errlog), daemon=True).start()
        return True, ""

    def _read_answer(self, proc: subprocess.Popen, errlog) -> None:
        out, _ = proc.communicate()
        errlog.close()
        text = (out or "").strip()
        if self.stopping:  # stop(): el proceso murió porque el servicio se apaga, no es un error
            return
        if proc.returncode == 0 or text:  # exit != 0 CON texto (stop length): es la respuesta que dio
            self._say(text or self.MSG_ERROR)
        else:
            self._say(self.MSG_ERROR)

    def _say(self, text: str) -> None:
        if self.on_say:
            self.on_say(text, brief=True)
        else:
            log(f"[orden] {self.title}: {text[:200]}")

    def stop(self) -> None:
        self.stopping = True
        if self._alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# -------------------------------------------------------------- orquestador
class Orchestrator:
    """Fachada: elige el backend, envía órdenes y (con start_supervisor) la mantiene viva."""

    def __init__(self, cfg: dict, on_say=None):
        self.cfg = cfg
        self.agent = cfg["agent"]
        self.title = self.agent[:1].upper() + self.agent[1:]
        self.on_say = on_say  # (texto, brief=…): solo lo usa el backend efímero (su voz es el servicio)
        self.backend = None
        self.reason = ""
        self._pick()

    def _pick(self):
        kind, self.reason = choose_backend(self.cfg)
        if kind != getattr(self.backend, "name", None):
            if self.backend:
                self.backend.stop()
            makers = {"herdr": HerdrBackend, "pi": PiRpcBackend,
                      "efimero": lambda c: EfimeroBackend(c, on_say=self.on_say)}
            make = makers.get(kind)
            self.backend = make(self.cfg) if make else None

    @property
    def kind(self) -> str | None:
        return getattr(self.backend, "name", None)

    def status(self, max_age: float = 0.0) -> str | None:
        """Estado actual; con max_age reutiliza el último si es reciente (el tray pregunta cada segundo)."""
        now = time.monotonic()
        cached = getattr(self, "_st", None)
        if max_age and cached and now - cached[0] < max_age:
            return cached[1]
        st = self.backend.status() if self.backend else None
        self._st = (now, st)
        return st

    def send(self, order: str) -> tuple[bool, str]:
        if self.backend is None:
            return False, self.reason
        ok, msg = self.backend.send(order)
        if not ok and self.backend.status() is None:
            threading.Thread(target=self.launch, daemon=True).start()  # que esté lista para la próxima
        return ok, msg

    def launch(self) -> tuple[bool, str]:
        self._pick()
        if self.backend is None:
            return False, self.reason
        return self.backend.launch()

    def new_session(self) -> str:
        """Sesión nueva (solo efimero): el próximo arranque no arrastra la conversación."""
        if self.backend is None:
            return self.reason
        new = getattr(self.backend, "new_session", None)
        return new() if callable(new) else "La sesión nueva solo aplica al backend efímero."

    def stop(self) -> None:
        if self.backend:
            self.backend.stop()

    def start_supervisor(self, every: float = 20.0) -> None:
        """Arranca a Nyx y la vuelve a levantar si desaparece (con espera tras un fallo).
        Con el backend efímero no hay nada que lanzar (status() nunca es None) y el ciclo
        queda en no-op, como debe ser."""

        def loop():
            backoff = 0.0
            while True:
                try:
                    ok = self._supervise_once()
                    if ok is not None:
                        backoff = 0.0 if ok else min(300.0, (backoff or 30.0) * 2)
                except Exception as e:  # noqa: BLE001
                    log(f"[orden] supervisor: {e}")
                    backoff = min(300.0, (backoff or 30.0) * 2)
                time.sleep(every + backoff)

        threading.Thread(target=loop, daemon=True).start()

    def _supervise_once(self) -> bool | None:
        """Un ciclo del supervisor: True/False si intentó lanzar (bien/mal); None si no había
        nada que lanzar. Extraído del loop para poder testearlo sin dormir."""
        self._pick()  # p.ej. herdr arrancó o se cerró: cambiar de backend
        if self.backend and self.backend.status() is None:
            ok, msg = self.backend.launch()
            log(f"[orden] {'arrancada' if ok else 'no arrancó'} ({self.kind}): {msg}")
            return ok
        return None


def launch(cfg: dict) -> int:
    """`nyx agent` sin servicio: solo el backend herdr tiene sentido fuera del servicio."""
    orch = Orchestrator(cfg)
    if orch.kind == "pi":
        print(f"Sin herdr, {orch.title} corre en segundo plano dentro del servicio de nyx "
              f"(systemctl --user start nyx).")
        return 1
    ok, msg = orch.launch()
    print(msg)
    return 0 if ok else 1
