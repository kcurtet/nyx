"""Órdenes por voz: "Trinity, …" va a la orquestadora (una sesión de pi) en vez de pegarse.

Dos formas de tenerla en marcha (backend):
  herdr: en su propio workspace de herdr — ves lo que hace y puede vigilar a tus agentes
         (pi-herdr en modo global).
  pi:    sin herdr — pi en segundo plano (`pi --mode rpc`) gestionado por el servicio de jerga.
         Mismas capacidades salvo los paneles y los agentes de herdr.
auto (por defecto): herdr si está instalado y en marcha; si no, pi; sin pi → no disponible.

El servicio la arranca solo y la vuelve a levantar si se cae (Supervisor).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .commands import _fold
from .config import STATE_DIR, log
from .platform_env import clean_child_env

AGENT_DIR = Path(__file__).resolve().parent / "trinity"


def match_wake(text: str, wake_words: list[str]) -> str | None:
    """Si `text` empieza por una palabra de activación, devuelve la orden (sin ella); si no, None.

    "Trinity, ve al repo jerga." → "Ve al repo jerga."   ·   "Trinity." → ""
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
    return r.returncode, data, out.strip()


def _pi_agent_dir() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")


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


def pi_args_for(cfg: dict, with_herdr: bool = True) -> list[str]:
    """Argumentos de pi para la orquestadora.

    isolated (por defecto): sin extensiones ni skills del usuario (nada de formularios
    interactivos que no se pueden contestar por voz, menos contexto), solo:
    [integración de estado de herdr + pi-herdr (modo global)] + su voz.
    """
    args = ["--skill", str(AGENT_DIR)]
    if cfg.get("isolated", True):
        args = ["--no-extensions", "--no-skills", *args]
        if with_herdr:
            state = _pi_agent_dir() / "extensions" / "herdr-agent-state.ts"
            if state.is_file():
                args += ["-e", str(state)]
            herdr_pkg = Path(os.path.expanduser(cfg.get("pi_herdr") or "")) if cfg.get("pi_herdr") else \
                _pi_agent_dir() / "git" / "github.com" / "kcurtet" / "pi-herdr"
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
    args += ["-e", str(AGENT_DIR / "voice.ts")]
    if cfg.get("model"):
        args += ["--model", cfg["model"]]
    return args


def herdr_available() -> bool:
    return shutil.which("herdr") is not None and _herdr("status")[0] == 0


def choose_backend(cfg: dict) -> tuple[str | None, str]:
    """(backend, motivo). backend None = no disponible; el motivo se dice en voz alta."""
    want = cfg.get("backend", "auto")
    has_pi = shutil.which("pi") is not None
    if not has_pi:
        return None, "Trinity no está disponible: falta pi. Instálalo para poder darme órdenes."
    if want == "herdr" or (want == "auto" and herdr_available()):
        if not shutil.which("herdr"):
            return None, "Trinity está configurada con herdr, pero herdr no está instalado."
        return "herdr", ""
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
        extra = ["--env", "PI_HERDR_SCOPE=global"] + (["--env", "JERGA_VOICE_DEBUG=1"] if self.cfg.get("debug") else [])
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
        pass  # su workspace sigue siendo tuyo: no lo cerramos al parar jerga


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
                env["JERGA_VOICE_DEBUG"] = "1"
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


# -------------------------------------------------------------- orquestador
class Orchestrator:
    """Fachada: elige el backend, envía órdenes y (con start_supervisor) la mantiene viva."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.agent = cfg["agent"]
        self.title = self.agent[:1].upper() + self.agent[1:]
        self.backend = None
        self.reason = ""
        self._pick()

    def _pick(self):
        kind, self.reason = choose_backend(self.cfg)
        if kind != getattr(self.backend, "name", None):
            if self.backend:
                self.backend.stop()
            self.backend = {"herdr": HerdrBackend, "pi": PiRpcBackend}.get(kind, lambda _c: None)(self.cfg)

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

    def stop(self) -> None:
        if self.backend:
            self.backend.stop()

    def start_supervisor(self, every: float = 20.0) -> None:
        """Arranca a Trinity y la vuelve a levantar si desaparece (con espera tras un fallo)."""

        def loop():
            backoff = 0.0
            while True:
                try:
                    self._pick()  # p.ej. herdr arrancó o se cerró: cambiar de backend
                    if self.backend and self.backend.status() is None:
                        ok, msg = self.backend.launch()
                        log(f"[orden] {'arrancada' if ok else 'no arrancó'} ({self.kind}): {msg}")
                        backoff = 0.0 if ok else min(300.0, (backoff or 30.0) * 2)
                except Exception as e:  # noqa: BLE001
                    log(f"[orden] supervisor: {e}")
                    backoff = min(300.0, (backoff or 30.0) * 2)
                time.sleep(every + backoff)

        threading.Thread(target=loop, daemon=True).start()


def launch(cfg: dict) -> int:
    """`jerga trinity` sin servicio: solo el backend herdr tiene sentido fuera del servicio."""
    orch = Orchestrator(cfg)
    if orch.kind == "pi":
        print(f"Sin herdr, {orch.title} corre en segundo plano dentro del servicio de jerga "
              f"(systemctl --user start jerga).")
        return 1
    ok, msg = orch.launch()
    print(msg)
    return 0 if ok else 1
