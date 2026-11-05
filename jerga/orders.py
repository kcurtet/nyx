"""Órdenes por voz: "Capitana, …" se envía a un agente pi en herdr en vez de pegarse.

  dictado → ¿empieza por la palabra de activación? → herdr agent prompt capitana "…"

`jerga capitana` arranca la orquestadora en una pestaña de herdr con su skill y
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

CAPITANA_DIR = Path(__file__).resolve().parent / "capitana"


def match_wake(text: str, wake_words: list[str]) -> str | None:
    """Si `text` empieza por una palabra de activación, devuelve la orden (sin ella); si no, None.

    "Capitana, ve al repo jerga." → "ve al repo jerga."   ·   "Capitana." → ""
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
            return False, f"No encuentro a la {self.agent}. Arráncala con jerga capitana."
        if st == "blocked":
            return False, f"La {self.agent} está esperando una aprobación en su panel."
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
        return False, f"No he podido mandar la orden a la {self.agent}. Mira su panel."


def launch(cfg: dict) -> int:
    """`jerga capitana`: crea la pestaña y arranca el agente (si no existe ya)."""
    orch = Orchestrator(cfg)
    if orch.status() is not None:
        print(f"La {orch.agent} ya está en marcha. (herdr agent focus {orch.agent} para verla)")
        return 0
    if not os.environ.get("HERDR_ENV") and _herdr("status")[0] != 0:
        print("herdr no está en marcha: arráncalo primero (herdr).")
        return 1
    code, data, out = _herdr("tab", "create", "--label", orch.agent, "--cwd", str(Path.home()), "--no-focus")
    pane = ((data or {}).get("result", {}).get("root_pane") or {}).get("pane_id")
    if code != 0 or not pane:
        print(f"No pude crear la pestaña: {out[:300]}")
        return 1
    pi_args = ["--skill", str(CAPITANA_DIR), "-e", str(CAPITANA_DIR / "voice.ts"), "--name", orch.agent]
    if cfg.get("model"):
        pi_args += ["--model", cfg["model"]]
    code, _, out = _herdr("agent", "start", orch.agent, "--kind", "pi", "--pane", pane, "--", *pi_args, timeout=60)
    if code != 0:
        print(f"No pude arrancar pi: {out[:300]}")
        return 1
    # No dar por buena la capitana hasta que pi esté de verdad esperando órdenes.
    _herdr("agent", "wait", orch.agent, "--until", "idle", "--timeout", "60000", timeout=65)
    print(f"Capitana en marcha en la pestaña '{orch.agent}'. Dile: «Capitana, …»")
    return 0
