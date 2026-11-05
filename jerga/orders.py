"""Órdenes por voz: "Trinity, …" se envía a un agente pi en herdr en vez de pegarse.

  dictado → ¿empieza por la palabra de activación? → herdr agent prompt trinity "…"

`jerga trinity` arranca la orquestadora en una pestaña de herdr con su skill y
la extensión de voz (que lee sus respuestas con `jerga say`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .commands import _fold
from .config import log
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


class Orchestrator:
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
        """Envía la orden. Devuelve (ok, mensaje para decir en voz alta si falla)."""
        st = self.status()
        if st is None:
            return False, f"No encuentro a {self.title}. Arráncala con jerga {self.agent}."
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


def _pi_agent_dir() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")


def _ext_file(path: Path) -> Path | None:
    """Ruta cargable con -e: el propio fichero, o el index.ts de un paquete."""
    if path.is_file():
        return path
    for name in ("index.ts", "index.js"):
        if (path / name).is_file():
            return path / name
    return None


def pi_args_for(cfg: dict) -> list[str]:
    """Argumentos de pi para la orquestadora.

    isolated (por defecto): sin extensiones ni skills del usuario (nada de formularios
    interactivos que no se pueden contestar por voz, menos contexto), solo:
    integración de estado de herdr + pi-herdr (modo global) + su voz.
    """
    args = ["--skill", str(AGENT_DIR)]
    if cfg.get("isolated", True):
        args = ["--no-extensions", "--no-skills", *args]
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
    args += ["-e", str(AGENT_DIR / "voice.ts")]
    if cfg.get("model"):
        args += ["--model", cfg["model"]]
    return args


def launch(cfg: dict) -> int:
    """`jerga trinity`: crea la pestaña y arranca el agente (si no existe ya)."""
    orch = Orchestrator(cfg)
    if orch.status() is not None:
        print(f"{orch.title} ya está en marcha. (herdr agent focus {orch.agent} para verla)")
        return 0
    if not os.environ.get("HERDR_ENV") and _herdr("status")[0] != 0:
        print("herdr no está en marcha: arráncalo primero (herdr).")
        return 1
    # PI_HERDR_SCOPE=global: pi-herdr ve y vigila TODOS los agentes de herdr (spec 004 de pi-herdr)
    extra = ["--env", "PI_HERDR_SCOPE=global"] + (["--env", "JERGA_VOICE_DEBUG=1"] if cfg.get("debug") else [])
    # Su propio workspace (por defecto): lo que ella despache con pi-herdr acaba ahí también,
    # separado de tus workspaces de trabajo.
    where = "workspace" if cfg.get("topology", "workspace") == "workspace" else "tab"
    code, data, out = _herdr(where, "create", "--label", orch.agent, "--cwd", str(Path.home()), "--no-focus", *extra)
    pane = ((data or {}).get("result", {}).get("root_pane") or {}).get("pane_id")
    if code != 0 or not pane:
        print(f"No pude crear el {where}: {out[:300]}")
        return 1
    pi_args = [*pi_args_for(cfg), "--name", orch.agent]
    code, _, out = _herdr("agent", "start", orch.agent, "--kind", "pi", "--pane", pane, "--", *pi_args, timeout=60)
    if code != 0:
        print(f"No pude arrancar pi: {out[:300]}")
        return 1
    # No dar por buena a la orquestadora hasta que pi esté de verdad esperando órdenes.
    _herdr("agent", "wait", orch.agent, "--until", "idle", "--timeout", "60000", timeout=65)
    print(f"{orch.title} en marcha en su {'workspace' if where == 'workspace' else 'pestaña'} '{orch.agent}'. Dile: «{orch.title}, …»")
    return 0
