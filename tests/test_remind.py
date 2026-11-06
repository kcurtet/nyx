"""Tarea 2 del plan 002: jerga remind — systemctl/systemd-run construidos y mockeados, nunca ejecutados."""
import io
import json
import shlex
from datetime import datetime
from types import SimpleNamespace

import pytest

import jerga.remind as R

AHORA = datetime(2026, 11, 9, 17, 0)  # lunes 9 de noviembre de 2026, 17:00


@pytest.fixture(autouse=True)
def _plataforma_linux(monkeypatch):
    """La suite corre como en Linux por defecto; el test del stub win32 se pone a win32 él mismo."""
    monkeypatch.setattr(R.sys, "platform", "linux")


@pytest.fixture(autouse=True)
def _jerga_arrancado(monkeypatch):
    """El servicio de jerga responde por defecto; el test del aviso lo pone a False él mismo."""
    monkeypatch.setattr(R, "is_running", lambda: True)


def _ctl(monkeypatch, units=(), timers=(), stop_rc=0, run_rc=0, units_rc=0, timers_rc=0):
    """Mockea which+run: registra los comandos y responde como systemctl (list/stop) y systemd-run."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "systemd-run":
            return SimpleNamespace(returncode=run_rc, stdout="", stderr="unit exists" if run_rc else "")
        op = cmd[2]
        if op == "list-units":
            out = json.dumps([{"unit": u, "description": d} for u, d in units])
            return SimpleNamespace(returncode=units_rc, stdout=out, stderr="boom" if units_rc else "")
        if op == "list-timers":
            out = json.dumps([{"unit": u, "next": t} for u, t in timers])
            return SimpleNamespace(returncode=timers_rc, stdout=out, stderr="boom" if timers_rc else "")
        return SimpleNamespace(returncode=stop_rc, stdout="", stderr="failed" if stop_rc else "")

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(R.shutil, "which", lambda b: f"/usr/bin/{b}")
    return calls


# --- parse_when ------------------------------------------------------------------------

def test_parse_when_minutos():
    assert R.parse_when("20m", AHORA) == ("--on-active=1200", "en 20 minutos")
    assert R.parse_when("20 m", AHORA) == ("--on-active=1200", "en 20 minutos")
    assert R.parse_when("20 minutos", AHORA) == ("--on-active=1200", "en 20 minutos")
    assert R.parse_when("1 minuto", AHORA) == ("--on-active=60", "en 1 minuto")


def test_parse_when_horas():
    assert R.parse_when("1h", AHORA) == ("--on-active=3600", "en 1 hora")
    assert R.parse_when("2 horas", AHORA) == ("--on-active=7200", "en 2 horas")


def test_parse_when_segundos():
    assert R.parse_when("90s", AHORA) == ("--on-active=90", "en 90 segundos")
    assert R.parse_when("90 s", AHORA) == ("--on-active=90", "en 90 segundos")
    assert R.parse_when("90 segundos", AHORA) == ("--on-active=90", "en 90 segundos")


def test_parse_when_hhmm_futuro_es_hoy():
    assert R.parse_when("18:00", AHORA) == ("--on-calendar=2026-11-09 18:00:00", "hoy a las 18:00")


def test_parse_when_hhmm_pasado_es_mañana():
    pasado = datetime(2026, 11, 9, 19, 0)
    assert R.parse_when("18:00", pasado) == ("--on-calendar=2026-11-10 18:00:00", "mañana a las 18:00")


def test_parse_when_hhmm_justo_ahora_o_hace_un_minuto_es_mañana():
    assert R.parse_when("17:00", AHORA) == ("--on-calendar=2026-11-10 17:00:00", "mañana a las 17:00")
    assert R.parse_when("16:59", AHORA) == ("--on-calendar=2026-11-10 16:59:00", "mañana a las 16:59")


def test_parse_when_basura_valueerror():
    for malo in ("patatas", "m", "-5m", "25:00", "18:65", "18:00:30", ""):
        with pytest.raises(ValueError):
            R.parse_when(malo, AHORA)


# --- fired_cmd -------------------------------------------------------------------------

def test_fired_cmd_notify_send_mas_jerga_say():
    assert R.fired_cmd("apagar el fuego") == [
        "sh", "-c",
        "notify-send -t 60000 Recordatorio 'apagar el fuego'; jerga say 'Recordatorio: apagar el fuego'",
    ]


def test_fired_cmd_escapa_comillas():
    cmd = R.fired_cmd("di 'hola'")[2]
    assert "'\\''" in cmd  # la comilla del texto no cierra el string de sh
    lex = shlex.shlex(io.StringIO(cmd), posix=True, punctuation_chars=True)  # el ; separa
    lex.whitespace_split = True
    partes = list(lex)  # sh recibe exactamente los argumentos originales
    assert "di 'hola'" in partes
    assert "Recordatorio: di 'hola'" in partes


# --- next_unit -------------------------------------------------------------------------

def test_next_unit_maximo_mas_uno(monkeypatch):
    calls = _ctl(monkeypatch, units=[("jerga-remind-2.timer", "jerga remind: a"),
                                     ("jerga-remind-5.timer", "jerga remind: b")])
    assert R.next_unit() == "jerga-remind-6"  # máximo + 1, no «cuántos hay» + 1
    assert calls == [["systemctl", "--user", "list-units", "jerga-remind-*", "--all", "--output=json"]]


def test_next_unit_sin_existente_empieza_en_uno(monkeypatch):
    _ctl(monkeypatch)
    assert R.next_unit() == "jerga-remind-1"


def test_next_unit_tambien_cuenta_servicios_rezagados(monkeypatch):
    _ctl(monkeypatch, units=[("jerga-remind-7.service", "jerga remind: viejo")])
    assert R.next_unit() == "jerga-remind-8"


# --- main: --list ----------------------------------------------------------------------

def test_list_vacio_sin_recordatorios_exit_0(monkeypatch, capsys):
    _ctl(monkeypatch)
    assert R.main(["--list"]) == R.EXIT_OK
    assert capsys.readouterr().out == "sin recordatorios\n"


def test_list_tolerante_con_la_leyenda_de_list_timers(monkeypatch, capsys):
    """list-timers imprime «N timers listed.» tras el JSON: el parse no debe romperse."""
    monkeypatch.setattr(R.subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="[]\n\n0 timers listed.\n", stderr=""))
    monkeypatch.setattr(R.shutil, "which", lambda b: f"/usr/bin/{b}")
    assert R.main(["--list"]) == R.EXIT_OK
    assert capsys.readouterr().out == "sin recordatorios\n"


def test_list_dos_con_cuando_y_texto(monkeypatch, capsys):
    _ctl(monkeypatch,
         units=[("jerga-remind-2.timer", "jerga remind: sacar la basura"),
                ("jerga-remind-5.timer", "jerga remind: apagar el fuego")],
         timers=[("jerga-remind-2.timer", "Mon 2026-11-09 18:00:00 CET"),
                 ("jerga-remind-5.timer", "Tue 2026-11-10 09:30:00 CET")])
    assert R.main(["--list"]) == R.EXIT_OK
    assert capsys.readouterr().out.splitlines() == [
        "2) Mon 2026-11-09 18:00 — sacar la basura",
        "5) Tue 2026-11-10 09:30 — apagar el fuego",
    ]


def test_list_systemctl_falla_exit_error(monkeypatch, capsys):
    _ctl(monkeypatch, timers_rc=1)
    assert R.main(["--list"]) == R.EXIT_ERROR
    assert "systemctl" in capsys.readouterr().out


def test_list_sin_systemctl(monkeypatch, capsys):
    monkeypatch.setattr(R.shutil, "which", lambda b: None)
    assert R.main(["--list"]) == R.EXIT_ERROR
    assert "systemctl" in capsys.readouterr().out


# --- main: --cancel --------------------------------------------------------------------

def test_cancel_para_timer_y_servicio(monkeypatch, capsys):
    calls = _ctl(monkeypatch,
                 units=[("jerga-remind-3.timer", "jerga remind: apagar el fuego")],
                 timers=[("jerga-remind-3.timer", "Mon 2026-11-09 18:00:00 CET")])
    assert R.main(["--cancel", "3"]) == R.EXIT_OK
    assert ["systemctl", "--user", "stop", "jerga-remind-3.timer", "jerga-remind-3.service"] in calls
    assert "apagar el fuego" in capsys.readouterr().out


def test_cancel_inexistente(monkeypatch, capsys):
    _ctl(monkeypatch, timers=[("jerga-remind-3.timer", "x")])
    assert R.main(["--cancel", "7"]) == R.EXIT_ERROR
    assert "7" in capsys.readouterr().out


def test_cancel_sin_numero_es_uso(monkeypatch, capsys):
    _ctl(monkeypatch)
    assert R.main(["--cancel"]) == R.EXIT_ERROR
    assert "uso" in capsys.readouterr().err


def test_cancel_falla_al_parar(monkeypatch, capsys):
    _ctl(monkeypatch, timers=[("jerga-remind-3.timer", "x")], stop_rc=1)
    assert R.main(["--cancel", "3"]) == R.EXIT_ERROR
    assert "cancelar" in capsys.readouterr().out


# --- main: crear -----------------------------------------------------------------------

def test_crear_20m_systemd_run_con_lista_de_args(monkeypatch, capsys):
    calls = _ctl(monkeypatch)
    assert R.main(["apagar el fuego", "en", "20m"]) == R.EXIT_OK
    assert calls[-1] == ["systemd-run", "--user", "--on-active=1200", "--unit=jerga-remind-1",
                         "--description=jerga remind: apagar el fuego",
                         *R.fired_cmd("apagar el fuego")]
    out = capsys.readouterr().out
    assert "apagar el fuego" in out and "en 20 minutos" in out
    assert "se pierde" not in out  # 20 m < 1 h: sin aviso de apagado


def test_crear_dos_no_se_pisan(monkeypatch):
    calls = _ctl(monkeypatch, units=[("jerga-remind-1.timer", "jerga remind: x")])
    assert R.main(["y", "en", "5m"]) == R.EXIT_OK
    assert calls[-1][3] == "--unit=jerga-remind-2"


def test_crear_mas_de_una_hora_avisa_se_pierde(monkeypatch, capsys):
    _ctl(monkeypatch)
    assert R.main(["x", "en", "90m"]) == R.EXIT_OK
    assert "se pierde" in capsys.readouterr().out


def test_crear_justo_una_hora_sin_aviso(monkeypatch, capsys):
    _ctl(monkeypatch)
    assert R.main(["x", "en", "1h"]) == R.EXIT_OK
    assert "se pierde" not in capsys.readouterr().out


def test_crear_hhmm_futuro_on_calendar(monkeypatch, capsys):
    class Fijo(datetime):  # reloj fijo: 17:00 del 9-11-2026
        @classmethod
        def now(cls, tz=None):
            return AHORA

    monkeypatch.setattr(R, "datetime", Fijo)
    calls = _ctl(monkeypatch)
    assert R.main(["apagar el fuego", "en", "18:00"]) == R.EXIT_OK
    assert calls[-1][2] == "--on-calendar=2026-11-09 18:00:00"
    assert calls[-1][3] == "--unit=jerga-remind-1"


def test_crear_texto_con_comillas_llega_escapado(monkeypatch):
    calls = _ctl(monkeypatch)
    assert R.main(["di 'hola'", "en", "20m"]) == R.EXIT_OK
    assert calls[-1][-3:] == R.fired_cmd("di 'hola'")
    assert "'\\''" in calls[-1][-1]


def test_crear_servicio_parado_avisa_que_no_sonara(monkeypatch, capsys):
    monkeypatch.setattr(R, "is_running", lambda: False)
    _ctl(monkeypatch)
    assert R.main(["x", "en", "20m"]) == R.EXIT_OK
    out = capsys.readouterr().out
    assert "no sonará" in out and "parado" in out


def test_crear_arrancado_no_avisa(monkeypatch, capsys):
    _ctl(monkeypatch)
    assert R.main(["x", "en", "20m"]) == R.EXIT_OK
    assert "no sonará" not in capsys.readouterr().out


def test_crear_cuando_basura(monkeypatch, capsys):
    _ctl(monkeypatch)
    assert R.main(["x", "en", "patatas"]) == R.EXIT_ERROR
    assert "no entiendo" in capsys.readouterr().err


def test_crear_sin_en_es_uso(monkeypatch, capsys):
    _ctl(monkeypatch)
    assert R.main(["apagar el fuego"]) == R.EXIT_ERROR
    assert "uso" in capsys.readouterr().err
    assert R.main([]) == R.EXIT_ERROR


def test_crear_sin_systemd_run(monkeypatch, capsys):
    _ctl(monkeypatch)
    monkeypatch.setattr(R.shutil, "which", lambda b: None if b == "systemd-run" else f"/usr/bin/{b}")
    assert R.main(["x", "en", "20m"]) == R.EXIT_ERROR
    assert "systemd-run" in capsys.readouterr().out


def test_crear_systemd_run_falla(monkeypatch, capsys):
    _ctl(monkeypatch, run_rc=1)
    assert R.main(["x", "en", "20m"]) == R.EXIT_ERROR
    assert "no pude crear" in capsys.readouterr().out


def test_crear_systemctl_no_responde(monkeypatch, capsys):
    _ctl(monkeypatch, units_rc=1)
    assert R.main(["x", "en", "20m"]) == R.EXIT_ERROR
    assert "systemctl" in capsys.readouterr().out


def test_stub_windows(monkeypatch, capsys):
    monkeypatch.setattr(R.sys, "platform", "win32")
    assert R.main(["x", "en", "20m"]) == R.EXIT_ERROR
    assert "windows" in capsys.readouterr().out.lower()
    assert R.main(["--list"]) == R.EXIT_ERROR
