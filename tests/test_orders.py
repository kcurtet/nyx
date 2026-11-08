import json
import os
import re
import stat
import sys
import time
from pathlib import Path

import pytest

import nyx.orders as o
from nyx.config import DEFAULTS

CFG = {**DEFAULTS["orders"], "isolated": True}


def test_eleccion_de_backend(monkeypatch):
    has = {"pi": True, "herdr": True, "ensure": True}
    monkeypatch.setattr(o.shutil, "which", lambda c: f"/usr/bin/{c}" if has.get(c) else None)
    monkeypatch.setattr(o, "_ensure_herdr_server", lambda timeout=8.0: (has["ensure"], ""))
    assert o.choose_backend(CFG) == ("herdr", "")
    has["ensure"] = False  # auto: ensure falla → pi, sin sermón
    assert o.choose_backend(CFG) == ("pi", "")
    has["herdr"] = False
    assert o.choose_backend(CFG) == ("pi", "")
    has["pi"] = False
    kind, why = o.choose_backend(CFG)  # pi primero: sin tocar herdr en una máquina sin pi
    assert kind is None and "falta pi" in why


def test_backend_herdr_explicito_sin_fallback(monkeypatch):  # A2
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/c")
    monkeypatch.setattr(o, "_ensure_herdr_server", lambda timeout=8.0: (False, "herdr server no responde"))
    kind, why = o.choose_backend({**CFG, "backend": "herdr"})
    assert kind is None and "arrancar herdr" in why  # error claro, sin caer a pi
    # y sin memoizar: el siguiente pick (supervisor) reintenta el ensure
    monkeypatch.setattr(o, "_ensure_herdr_server", lambda timeout=8.0: (True, ""))
    assert o.choose_backend({**CFG, "backend": "herdr"}) == ("herdr", "")


def test_backend_herdr_sin_instalar(monkeypatch):
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/pi" if c == "pi" else None)
    kind, why = o.choose_backend({**CFG, "backend": "herdr"})
    assert kind is None and "no está instalado" in why


def test_orquestador_sin_pi_dice_por_que(monkeypatch):
    monkeypatch.setattr(o.shutil, "which", lambda c: None)
    orch = o.Orchestrator(CFG)
    ok, msg = orch.send("hola")
    assert not ok and "falta pi" in msg
    assert orch.kind is None and orch.status() is None


FAKE_PI = r'''#!/usr/bin/env python3
import json, sys, time
for line in sys.stdin:
    cmd = json.loads(line)
    with open(sys.argv[-1] if sys.argv[-1].endswith(".jsonl") else "/dev/null", "a") as f:
        pass
    print(json.dumps({"type": "agent_start"}), flush=True)
    time.sleep(0.3)
    print(json.dumps({"type": "agent_end", "messages": [], "got": cmd}), flush=True)
'''


@pytest.mark.skipif(sys.platform == "win32", reason="pi falso como script ejecutable de Unix")
def test_backend_pi_rpc(tmp_path, monkeypatch):
    fake = tmp_path / "bin" / "pi"
    fake.parent.mkdir()
    fake.write_text(FAKE_PI)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(o, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()
    b = o.PiRpcBackend(CFG)
    b.sessions = tmp_path / "state" / "s"
    assert b.status() is None
    ok, _ = b.launch()
    assert ok and b.status() == "idle"
    ok, _ = b.send("¿qué hora es?")
    assert ok and b.status() == "working"
    deadline = time.time() + 5
    while b.status() != "idle" and time.time() < deadline:
        time.sleep(0.05)
    assert b.status() == "idle"
    b.stop()
    assert b.status() is None
    assert json.dumps  # usado por el pi falso


def test_args_sin_herdr():
    args = o.pi_args_for(CFG, with_herdr=False)
    assert "--no-extensions" in args and not any("herdr" in a for a in args)
    assert args[-1].endswith("voice.ts") or "--model" in args


def test_skill_apunta_al_directorio_nuevo():
    # --skill al nuevo dir (nyx/nyx), no al viejo trinity: SKILL.md y voice.ts viven ahí
    assert o.AGENT_DIR.name == "nyx" and (o.AGENT_DIR / "SKILL.md").is_file()
    for args in (o.pi_args_for(CFG, with_herdr=False), o.pi_args_for({"isolated": False})):
        skill = Path(args[args.index("--skill") + 1])
        assert skill == o.AGENT_DIR and skill.name == "nyx"
        assert str(o.AGENT_DIR / "voice.ts") in args


# ------------------------------------------------------- la skill es de Nyx
SKILL = (o.AGENT_DIR / "SKILL.md").read_text(encoding="utf-8")


def test_la_skill_se_llama_nyx():
    assert re.search(r"^name: nyx$", SKILL, re.MULTILINE)
    assert "Eres **Nyx**" in SKILL


def test_la_skill_no_ensena_comandos_muertos():
    # s/jerga→nyx/ mecánico: nada de comandos, rutas o ejemplos con el nombre viejo
    assert "jerga" not in SKILL and "trinity" not in SKILL.lower()


def test_los_comandos_citados_empiezan_por_nyx():
    citados = re.findall(r"`(nyx|jerga)\s", SKILL)
    assert citados and set(citados) == {"nyx"}  # hay comandos y todos son `nyx …`


def test_herdr_error_json_es_fallo(monkeypatch):  # A5: rc 0 + {"error":…} → rc efectivo != 0
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/herdr")

    class R:
        def __init__(self, stdout):
            self.returncode, self.stdout, self.stderr = 0, stdout, ""

    def fake_run(stdout):
        return lambda cmd, **kw: R(stdout)

    monkeypatch.setattr(o.subprocess, "run", fake_run('{"id":"cli:agent:get","error":{"code":"server_not_running"}}'))
    rc, data, _ = o._herdr("agent", "get", "nyx-agent")
    assert rc == 1 and data["error"]["code"] == "server_not_running"  # rc falla, data se conserva
    monkeypatch.setattr(o.subprocess, "run", fake_run('{"id":"x","result":{}}'))
    rc, data, _ = o._herdr("agent", "get", "nyx-agent")
    assert rc == 0 and data == {"id": "x", "result": {}}  # sin "error": rc intacto


def test_herdr_status_none_con_servidor_caido(monkeypatch):
    # D4 de punta a punta: rc 0 + error JSON (herdr 0.9.3) → status() debe dar None, no "unknown"
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/herdr")

    class R:
        returncode = 0
        stdout = '{"id":"x","error":{"code":"server_not_running"}}'
        stderr = ""

    monkeypatch.setattr(o.subprocess, "run", lambda cmd, **kw: R())
    b = o.HerdrBackend({**CFG})
    assert b.status() is None


# ------------------------------------------- herdr disponible y bajo demanda (005)
def test_herdr_available_mira_el_servidor_no_el_rc(monkeypatch):
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/herdr")
    # rc 0 pero servidor parado: hoy herdr_available() devuelve True (bug)
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (0, {"server": {"running": False}}, ""))
    assert o._herdr_server_running() is False
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (0, {"server": {"running": True}}, ""))
    assert o._herdr_server_running() is True
    assert o.herdr_available() is True


def test_herdr_server_running_fallback_textual(monkeypatch):  # A8: herdr viejo sin --json
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (0, None, "client:\n  v\n\nserver:\n  status: running\n"))
    assert o._herdr_server_running() is True
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (0, None, "server:\n  status: not running\n"))
    assert o._herdr_server_running() is False


class _FakeProc:  # proceso herdr server "lanzado": vivo y sin esperar
    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


def _reloj_rapido():
    """monotonic() que avanza 1 s por llamada: el bucle termina solo por deadline, no por intentos."""
    t = [0.0]

    def now():
        t[0] += 1.0
        return t[0]

    return now


def test_ensure_no_arranca_si_ya_running(monkeypatch):  # A3: cero procesos nuevos
    spawns = []
    monkeypatch.setattr(o, "_herdr_server_running", lambda: True)
    monkeypatch.setattr(o.subprocess, "Popen", lambda cmd, **k: spawns.append(cmd) or _FakeProc())
    ok, why = o._ensure_herdr_server()
    assert ok and not spawns


def test_ensure_arranca_y_espera_running(monkeypatch, tmp_path):
    state = {"running": False, "spawns": []}
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/herdr")
    monkeypatch.setattr(o, "_herdr_server_running", lambda: state["running"])
    monkeypatch.setattr(o.time, "sleep", lambda s: state.__setitem__("running", True))
    monkeypatch.setattr(o.subprocess, "Popen", lambda cmd, **k: state["spawns"].append(cmd) or _FakeProc())
    monkeypatch.setattr(o, "STATE_DIR", tmp_path)
    monkeypatch.setattr(o, "_SERVER_STARTED_BY_NYX", False)
    ok, why = o._ensure_herdr_server()
    assert ok and state["spawns"] == [["/usr/bin/herdr", "server"]]
    assert o._SERVER_STARTED_BY_NYX  # lo lanzó nyx: lo cuenta el doctor (D5)
    assert (tmp_path / "herdr-server.log").exists()  # el log del server vive bajo STATE_DIR


def test_ensure_agota_el_plazo_sin_running(monkeypatch):  # A2 (parte del mecanismo)
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/herdr")
    monkeypatch.setattr(o, "_herdr_server_running", lambda: False)
    monkeypatch.setattr(o.subprocess, "Popen", lambda cmd, **k: _FakeProc())
    monkeypatch.setattr(o.time, "sleep", lambda s: None)  # sin dormir: corta el deadline wall-clock
    monkeypatch.setattr(o.time, "monotonic", _reloj_rapido())
    ok, why = o._ensure_herdr_server()
    assert not ok and why
