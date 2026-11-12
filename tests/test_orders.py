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


FAKE_PI_P = r'''#!/usr/bin/env python3
import json, os, sys, time
if os.environ.get("NYX_FAKE_LOG"):
    with open(os.environ["NYX_FAKE_LOG"], "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
time.sleep(float(os.environ.get("NYX_FAKE_SLEEP", "0")))
rc = int(os.environ.get("NYX_FAKE_RC", "0"))
out = os.environ.get("NYX_FAKE_OUT", "hecho")
if out:
    print(out, flush=True)
sys.exit(rc)
'''


def _fake_pi_oneshot(tmp_path, monkeypatch, **env):
    """pi falso para el backend efímero: loggea argv+cwd en NYX_FAKE_LOG y responde según
    NYX_FAKE_OUT / NYX_FAKE_RC / NYX_FAKE_SLEEP (patrón FAKE_PI: nunca un pi real en CI)."""
    fake = tmp_path / "bin" / "pi"
    fake.parent.mkdir(exist_ok=True)
    fake.write_text(FAKE_PI_P)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(o, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir(exist_ok=True)
    log = tmp_path / "spawns.jsonl"
    monkeypatch.setenv("NYX_FAKE_LOG", str(log))
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return log


def _said(said, n=1, deadline=5.0):
    """Espera (sin dormir de más) a que on_say haya sido llamado n veces."""
    end = time.time() + deadline
    while time.time() < end:
        if len(said) >= n:
            return said[:n]
        time.sleep(0.05)
    raise AssertionError(f"on_say llamado {len(said)} veces, esperaba {n}")


def _spawns(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def _wait_spawns(log, n=1, deadline=5.0):
    """Espera a que el pi falso haya loggeado n spawns (arranca en su propio proceso)."""
    end = time.time() + deadline
    while time.time() < end:
        if log.exists() and len(_spawns(log)) >= n:
            return _spawns(log)
        time.sleep(0.05)
    raise AssertionError(f"{len(_spawns(log)) if log.exists() else 0} spawns, esperaba {n}")


@pytest.mark.skipif(sys.platform == "win32", reason="pi falso como script ejecutable de Unix")
def test_efimero_arranca_y_habla(tmp_path, monkeypatch):  # A1: one-shot con --continue y voz del backend
    log = _fake_pi_oneshot(tmp_path, monkeypatch)
    said = []
    b = o.EfimeroBackend(CFG, on_say=lambda t, brief=False: said.append((t, brief)))
    ok, msg = b.send("¿qué branch tengo?")
    assert ok and msg == ""  # no bloquea el hilo de voz
    text, brief = _said(said)[0]
    assert text == "hecho" and brief is True  # respuesta SOLO por voz, breve
    assert b.status() == "idle"  # muere al terminar
    assert len(_spawns(log)) == 1  # UN pi one-shot
    argv = _spawns(log)[0]["argv"]
    assert "-p" in argv and "--continue" in argv
    assert argv[argv.index("--") + 1] == "¿qué branch tengo?"  # «--» justo antes de la orden
    assert argv[argv.index("--session-dir") + 1] == str(b.sessions)  # la sesión compartida del backend pi
    assert not any(a.endswith("voice.ts") for a in argv)  # sin voice.ts: la voz la pone el backend
    assert _spawns(log)[0]["cwd"] == str(Path.home())  # cwd pinneado (pi agrupa sesiones por cwd)


@pytest.mark.skipif(sys.platform == "win32", reason="pi falso como script ejecutable de Unix")
def test_efimero_rechaza_ocupada(tmp_path, monkeypatch):  # A2: trabajando → rechazo, sin cola
    log = _fake_pi_oneshot(tmp_path, monkeypatch, NYX_FAKE_SLEEP="10")
    b = o.EfimeroBackend(CFG, on_say=lambda t, brief=False: None)
    ok, _ = b.send("primera")
    assert ok and b.status() == "working"
    ok, msg = b.send("segunda")
    assert not ok and "ocupada" in msg
    assert len(_wait_spawns(log)) == 1  # NO se lanza otro pi
    b.stop()
    assert b.status() == "idle"


@pytest.mark.skipif(sys.platform == "win32", reason="pi falso como script ejecutable de Unix")
def test_efimero_error_sin_salida(tmp_path, monkeypatch):  # A3: exit != 0 sin stdout → voz de error
    _fake_pi_oneshot(tmp_path, monkeypatch, NYX_FAKE_RC="1", NYX_FAKE_OUT="")
    said = []
    b = o.EfimeroBackend(CFG, on_say=lambda t, brief=False: said.append((t, brief)))
    assert b.send("explota")[0]
    text, brief = _said(said)[0]
    assert text and text != "hecho" and brief is True  # error de una frase, no crash
    assert b.status() == "idle"  # vuelve a reposo


@pytest.mark.skipif(sys.platform == "win32", reason="pi falso como script ejecutable de Unix")
def test_efimero_texto_parcial_se_lee(tmp_path, monkeypatch):  # stop length: exit 1 CON texto
    _fake_pi_oneshot(tmp_path, monkeypatch, NYX_FAKE_RC="1", NYX_FAKE_OUT="respuesta parcial")
    said = []
    b = o.EfimeroBackend(CFG, on_say=lambda t, brief=False: said.append((t, brief)))
    assert b.send("larga")[0]
    assert _said(said)[0] == ("respuesta parcial", True)  # es la respuesta que alcanzó a dar


@pytest.mark.skipif(sys.platform == "win32", reason="pi falso como script ejecutable de Unix")
def test_efimero_mismo_session_dir(tmp_path, monkeypatch):  # A4: misma sesión y mismo cwd
    log = _fake_pi_oneshot(tmp_path, monkeypatch)
    said = []
    b = o.EfimeroBackend(CFG, on_say=lambda t, brief=False: said.append((t, brief)))
    assert b.send("una")[0]
    _said(said)
    assert b.send("dos")[0]
    _said(said, n=2)
    s1, s2 = _spawns(log)
    assert s1["cwd"] == s2["cwd"] == str(Path.home())
    sd = s1["argv"][s1["argv"].index("--session-dir") + 1]
    assert s2["argv"][s2["argv"].index("--session-dir") + 1] == sd
    assert "--continue" in s2["argv"]  # la segunda retoma la conversación


@pytest.mark.skipif(sys.platform == "win32", reason="pi falso como script ejecutable de Unix")
def test_efimero_status_y_stop(tmp_path, monkeypatch):  # A6/A8 + D5: idle/working, nunca None
    _fake_pi_oneshot(tmp_path, monkeypatch, NYX_FAKE_SLEEP="10")
    b = o.EfimeroBackend(CFG)
    assert b.status() == "idle"  # en reposo = disponible, NO None (nada que arrancar)
    ok, msg = b.launch()  # D5: nada que lanzar; el mismo texto sirve para `nyx agent`
    assert ok and "Dile" in msg and "arrancan" in msg
    assert b.send("larga")[0]
    assert b.status() == "working"
    b.stop()  # A8: se termina el proceso
    assert b.status() == "idle"


def test_args_sin_herdr():
    args = o.pi_args_for(CFG, with_herdr=False)
    assert "--no-extensions" in args and not any("herdr" in a for a in args)
    assert args[-1].endswith("voice.ts") or "--model" in args


def test_args_voice_false_omite_voice_ts():
    # efímero: sin voice.ts (la voz la pone el backend vía on_say) — con ella, doble lectura
    args = o.pi_args_for(CFG, with_herdr=False, voice=False)
    assert not any(a.endswith("voice.ts") for a in args)
    assert "--skill" in args  # la skill de Nyx sí viaja
    full = o.pi_args_for(CFG, with_herdr=False)
    assert str(o.AGENT_DIR / "voice.ts") in full and str(o.AGENT_DIR / "voice.ts") not in args


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


def test_doctor_avisa_si_nyx_arranco_herdr(capsys, monkeypatch):  # D5
    from nyx import doctor as d

    def seccion(flag):
        monkeypatch.setattr(o, "choose_backend", lambda cfg: ("herdr", ""))
        monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (1, None, ""))  # agente parado
        monkeypatch.setattr(o, "_SERVER_STARTED_BY_NYX", flag)
        d._doctor_orders(d.Report(), CFG)
        return capsys.readouterr().out

    assert "herdr server arrancado por nyx" in seccion(True)
    assert "herdr server arrancado por nyx" not in seccion(False)
