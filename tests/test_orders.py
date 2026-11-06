import json
import os
import stat
import sys
import time

import pytest

import jerga.orders as o
from jerga.config import DEFAULTS

CFG = {**DEFAULTS["orders"], "isolated": True}


def test_eleccion_de_backend(monkeypatch):
    has = {"pi": True, "herdr": True}
    monkeypatch.setattr(o.shutil, "which", lambda c: f"/usr/bin/{c}" if has.get(c) else None)
    monkeypatch.setattr(o, "herdr_available", lambda: has["herdr"])
    assert o.choose_backend(CFG) == ("herdr", "")
    has["herdr"] = False
    assert o.choose_backend(CFG) == ("pi", "")  # sin herdr: pi en segundo plano
    has["pi"] = False
    kind, why = o.choose_backend(CFG)
    assert kind is None and "falta pi" in why  # sin pi: error claro
    has.update(pi=True, herdr=False)
    kind, why = o.choose_backend({**CFG, "backend": "herdr"})
    assert kind is None and "herdr no está instalado" in why


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
