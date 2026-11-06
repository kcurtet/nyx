"""Tarea 3 del plan 003: entorno nyx — alias jerga, NYX_*, socket nyx.sock y par uinput/autofiltro."""
from __future__ import annotations

import importlib
import os
import selectors
import sys
from pathlib import Path

import pytest

import nyx.app
import nyx.config
import nyx.hotkey
import nyx.migrate
import nyx.platform_env
from nyx.output import UINPUT_NAME, UINPUT_TAG, teclado_simulado

AVISO = "jerga ahora es nyx"


# ------------------------------------------------------------------ alias (D3)
def test_alias_avisa_una_vez_por_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["/home/x/.local/bin/jerga", "toggle"])
    nyx.app._aviso_alias()
    assert capsys.readouterr().err.strip() == AVISO
    assert (nyx.config.STATE_DIR / ".alias-avisado").exists()  # marker (STATE_DIR aislado por conftest)
    nyx.app._aviso_alias()
    assert capsys.readouterr().err == ""  # segunda vez: silencio


def test_sin_alias_no_avisa_ni_marca(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["/home/x/.local/bin/nyx", "toggle"])
    nyx.app._aviso_alias()
    assert capsys.readouterr().err == ""
    assert not (nyx.config.STATE_DIR / ".alias-avisado").exists()


def test_alias_de_windows_por_entorno(tmp_path, monkeypatch, capsys):
    # jerga.cmd llama a nyx.exe marcando NYX_ALIAS: argv[0] ya no delata el alias
    monkeypatch.setattr(sys, "argv", ["C:\\tools\\nyx.exe", "toggle"])
    monkeypatch.setenv("NYX_ALIAS", "jerga")
    nyx.app._aviso_alias()
    assert capsys.readouterr().err.strip() == AVISO


def test_el_marker_no_borra_el_aviso_si_falla_la_escritura(tmp_path, monkeypatch, capsys):
    # STATE_DIR sin permisos: se avisa igual (y se reintentará la próxima vez)
    monkeypatch.setattr(sys, "argv", ["/home/x/.local/bin/jerga"])
    monkeypatch.setattr(nyx.config, "STATE_DIR", Path("/proc/no-puedo-escribir-aqui"))
    nyx.app._aviso_alias()
    assert capsys.readouterr().err.strip() == AVISO


# ------------------------------------------------------------------ NYX_*
def test_entorno_nyx_env_ready(monkeypatch):
    assert nyx.platform_env._FLAG == "NYX_ENV_READY"
    reejecutado = []
    monkeypatch.setattr(nyx.platform_env.os, "execve", lambda *a: reejecutado.append(a))  # cinturón: nunca re-ejecutar
    monkeypatch.setenv("NYX_ENV_READY", "1")
    nyx.platform_env.prepare()  # con el flag puesto: vuelve sin hacer nada
    assert not reejecutado


def test_entorno_hijo_limpio(monkeypatch):
    for k in ("NYX_ENV_READY", "LD_PRELOAD", "NYX_ALIAS"):
        monkeypatch.setenv(k, "1")
    child = nyx.platform_env.clean_child_env()
    assert "NYX_ENV_READY" not in child and "LD_PRELOAD" not in child and "NYX_ALIAS" not in child


def test_key_debug_se_llama_nyx(monkeypatch):
    monkeypatch.delenv("JERGA_KEY_DEBUG", raising=False)
    monkeypatch.setenv("NYX_KEY_DEBUG", "1")
    assert importlib.reload(nyx.hotkey)._KEY_DEBUG is True
    monkeypatch.delenv("NYX_KEY_DEBUG")
    assert importlib.reload(nyx.hotkey)._KEY_DEBUG is False


def test_socket_de_control_es_nyx():
    assert nyx.hotkey.SOCKET_PATH.name == "nyx.sock"


def test_debug_de_vision_se_llama_nyx():
    src = (Path(nyx.app.__file__).parent / "vision.py").read_text(encoding="utf-8")
    assert 'NYX_DEBUG' in src and 'JERGA_DEBUG' not in src


def test_extension_de_voz_entorno_nyx():
    ts = (Path(nyx.app.__file__).parent / "trinity" / "voice.ts").read_text(encoding="utf-8")
    assert "NYX_BIN" in ts and "NYX_VOICE_DEBUG" in ts
    assert "JERGA_" not in ts  # sin variables viejas
    assert '"state", "nyx"' in ts and '"state", "jerga"' not in ts  # log en ~/.local/state/nyx
    assert ts.count('"jerga"') == 1  # y jerga solo como fallback del binario (durante el alias)


# ------------------------------------------------------- par uinput/autofiltro
def test_par_uinput_autofiltro():
    # el nombre del teclado virtual lleva el tag que los oyentes excluyen: par ATÓMICO
    assert UINPUT_TAG == "nyx"
    assert UINPUT_NAME == "nyx-virtual-keyboard"
    assert teclado_simulado(UINPUT_NAME)
    assert not teclado_simulado("AT Translated Set 2 keyboard")
    assert teclado_simulado("YDOTOOL virtual keyboard")  # ydotool sigue filtrado, May/min da igual


def test_los_filtros_derivan_del_par():
    # ni hotkey ni keys() escriben cadenas propias: endurecer el par a nivel de fuente
    import inspect

    for fn in (nyx.hotkey.EvdevListener._scan, nyx.app.keys):
        src = inspect.getsource(fn)
        assert "teclado_simulado" in src
        assert "jerga" not in src


def test_scan_ignora_el_teclado_virtual(monkeypatch):
    evdev = pytest.importorskip("evdev")

    class FakeDev:
        def __init__(self, path, name):
            self.path, self.name = path, name
            self.r, self.w = os.pipe()

        def fileno(self):
            return self.r

        def capabilities(self):
            from evdev import ecodes

            return {ecodes.EV_KEY: [ecodes.ecodes["KEY_RIGHTCTRL"]]}

    virtual, real = FakeDev("/dev/input/event9", UINPUT_NAME), FakeDev("/dev/input/event10", "Keychron K2")
    monkeypatch.setattr(evdev, "list_devices", lambda: [virtual.path, real.path])
    monkeypatch.setattr(evdev, "InputDevice", lambda p: virtual if p == virtual.path else real)
    ptt = nyx.hotkey.PushToTalk("hold", lambda: None, lambda: None, lambda: None)
    listener = nyx.hotkey.EvdevListener("KEY_RIGHTCTRL", ptt)
    sel = selectors.DefaultSelector()
    try:
        assert listener._scan(sel) == ["Keychron K2"]  # el virtual queda fuera: no nos oímos
    finally:
        sel.close()
        for d in (virtual, real):
            os.close(d.r)
            os.close(d.w)


# ------------------------------------------------- subcomando agent (y trinity)
def test_subcomando_agent_y_alias_trinity(monkeypatch, capsys):
    mandados = []
    monkeypatch.setattr(nyx.migrate, "run", lambda home=None: [])  # nada real que migrar
    monkeypatch.setattr(nyx.hotkey, "is_running", lambda: True)
    monkeypatch.setattr(nyx.hotkey, "send_command",
                        lambda cmd, payload="", timeout=5: mandados.append(cmd) or "ok")
    for argv, esperado in [(["nyx", "agent"], "agent-start"),
                           (["nyx", "agent", "restart"], "agent-restart"),
                           (["nyx", "trinity"], "agent-start"),  # alias silencioso
                           (["nyx", "trinity", "restart"], "agent-restart")]:
        monkeypatch.setattr(sys, "argv", argv)
        nyx.app.main()
        assert mandados[-1] == esperado
    assert capsys.readouterr().err == ""  # silencioso de verdad (ni aviso ni ruido)


def test_protocolo_de_control_del_agente():
    assert {"agent-start", "agent-restart"} <= nyx.hotkey.SYNC_COMMANDS
    assert not {"trinity-start", "trinity-restart"} & nyx.hotkey.SYNC_COMMANDS
