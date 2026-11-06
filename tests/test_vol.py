"""Tarea 1 del plan 002: jerga vol — comandos de pactl construidos y mockeados, nunca ejecutados."""
from types import SimpleNamespace

import jerga.vol as V

# salida real de `pactl get-sink-volume @DEFAULT_SINK@` en este equipo (PipeWire)
PACTL_VOLUME = (
    "Volume: front-left: 29966 /  46% / -17.32 dB,   front-right: 29966 /  46% / -17.32 dB\n"
    "        overall balance 0.00\n"
)


def _vol(n: int) -> str:
    """Salida de get-sink-volume como la generaría pactl para un volumen de n %."""
    raw = int(n * 65536 / 100)
    return (f"Volume: front-left: {raw} /  {n}% / -17.32 dB,   "
            f"front-right: {raw} /  {n}% / -17.32 dB\n")


def _pactl(monkeypatch, volume=PACTL_VOLUME, mute="Mute: yes\n", rc=0):
    """Mockea which+run: registra los comandos y responde como pactl (sin ejecutar nada real)."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "get-sink-volume":
            out = volume
        elif cmd[1] == "get-sink-mute":
            out = mute
        else:  # set-sink-volume / set-sink-mute: no dicen nada
            out = ""
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")

    monkeypatch.setattr(V.subprocess, "run", fake_run)
    monkeypatch.setattr(V.shutil, "which", lambda b: "/usr/bin/pactl")
    return calls


# --- build_args ------------------------------------------------------------------------

def test_build_args_up_y_down():
    assert V.build_args("up") == ["set-sink-volume", "@DEFAULT_SINK@", "+10%"]
    assert V.build_args("down") == ["set-sink-volume", "@DEFAULT_SINK@", "-10%"]


def test_build_args_mute_es_set_sink_mute_toggle():
    assert V.build_args("mute") == ["set-sink-mute", "@DEFAULT_SINK@", "toggle"]


def test_build_args_porcentaje_fijo():
    assert V.build_args(30) == ["set-sink-volume", "@DEFAULT_SINK@", "30%"]
    assert V.build_args(0) == ["set-sink-volume", "@DEFAULT_SINK@", "0%"]
    assert V.build_args(100) == ["set-sink-volume", "@DEFAULT_SINK@", "100%"]


# --- read_volume ----------------------------------------------------------------------

def test_read_volume_parsea_salida_real(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=PACTL_VOLUME, stderr="")

    monkeypatch.setattr(V.subprocess, "run", fake_run)
    assert V.read_volume() == "46%"
    assert calls == [["pactl", "get-sink-volume", "@DEFAULT_SINK@"]]


def test_read_volume_con_porcentaje_distinto(monkeypatch):
    fake = SimpleNamespace(returncode=0, stdout=_vol(30), stderr="")
    monkeypatch.setattr(V.subprocess, "run", lambda cmd, **kw: fake)
    assert V.read_volume() == "30%"


def test_read_volume_fallo_o_basura_da_none(monkeypatch):
    monkeypatch.setattr(V.subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="x"))
    assert V.read_volume() is None
    monkeypatch.setattr(V.subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="nada que parsear", stderr=""))
    assert V.read_volume() is None

    def boom(cmd, **kw):
        raise OSError("sin pactl")

    monkeypatch.setattr(V.subprocess, "run", boom)
    assert V.read_volume() is None


# --- main: contrato de salida ----------------------------------------------------------

def test_main_sin_args_sube_diez_y_dicte_volumen(monkeypatch, capsys):
    calls = _pactl(monkeypatch)
    assert V.main([]) == V.EXIT_OK
    assert calls[0] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"]
    assert calls[1] == ["pactl", "get-sink-volume", "@DEFAULT_SINK@"]
    assert capsys.readouterr().out == "volumen al 46 %\n"  # una línea: el % que reporta pactl


def test_main_down_baja_diez(monkeypatch, capsys):
    calls = _pactl(monkeypatch)
    assert V.main(["down"]) == V.EXIT_OK
    assert calls[0] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"]


def test_main_fija_porcentaje(monkeypatch, capsys):
    calls = _pactl(monkeypatch, volume=_vol(30))
    assert V.main(["30"]) == V.EXIT_OK
    assert calls[0] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "30%"]
    assert capsys.readouterr().out == "volumen al 30 %\n"


def test_main_porcentaje_con_simbolo_tambien_vale(monkeypatch, capsys):
    calls = _pactl(monkeypatch, volume=_vol(70))
    assert V.main(["70%"]) == V.EXIT_OK
    assert calls[0] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "70%"]


def test_main_clamp_alto_con_aviso_no_error(monkeypatch, capsys):
    calls = _pactl(monkeypatch, volume=_vol(100))
    assert V.main(["130"]) == V.EXIT_OK
    assert calls[0] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"]
    out = capsys.readouterr().out
    assert out.count("\n") == 1  # una línea, no un error
    assert "100 %" in out and "130" in out


def test_main_clamp_bajo_con_aviso(monkeypatch, capsys):
    _pactl(monkeypatch, volume=_vol(0))
    assert V.main(["-20"]) == V.EXIT_OK
    out = capsys.readouterr().out
    assert "0 %" in out and "-20" in out


def test_main_mute_a_cortado(monkeypatch, capsys):
    calls = _pactl(monkeypatch, mute="Mute: yes\n")
    assert V.main(["mute"]) == V.EXIT_OK
    assert calls[0] == ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]
    assert calls[1] == ["pactl", "get-sink-mute", "@DEFAULT_SINK@"]
    assert capsys.readouterr().out == "muteado\n"


def test_main_mute_a_sonando(monkeypatch, capsys):
    _pactl(monkeypatch, mute="Mute: no\n")
    assert V.main(["mute"]) == V.EXIT_OK
    assert capsys.readouterr().out == "con sonido\n"


def test_main_mute_sin_lectura_es_neutro(monkeypatch, capsys):
    """get-sink-mute falla tras el toggle: ni «muteado» ni «con sonido» — la línea honesta."""

    def fake_run(cmd, **kwargs):
        if cmd[1] == "get-sink-mute":
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(V.subprocess, "run", fake_run)
    monkeypatch.setattr(V.shutil, "which", lambda b: "/usr/bin/pactl")
    assert V.main(["mute"]) == V.EXIT_OK
    assert capsys.readouterr().out == "mute conmutado\n"


# --- main: errores y stub -------------------------------------------------------------

def test_main_sin_pactl_exit_error(monkeypatch, capsys):
    monkeypatch.setattr(V.shutil, "which", lambda b: None)
    assert V.main(["up"]) == V.EXIT_ERROR
    assert "pactl" in capsys.readouterr().out


def test_main_pactl_falla_exit_error(monkeypatch, capsys):
    _pactl(monkeypatch, rc=1)
    assert V.main(["up"]) == V.EXIT_ERROR
    assert "volumen" in capsys.readouterr().out.lower()


def test_main_argumento_basura_es_uso(monkeypatch, capsys):
    _pactl(monkeypatch)
    assert V.main(["patatas"]) == V.EXIT_ERROR
    assert "uso" in capsys.readouterr().err


def test_main_stub_windows(monkeypatch, capsys):
    monkeypatch.setattr(V.sys, "platform", "win32")
    assert V.main([]) == V.EXIT_ERROR
    assert "windows" in capsys.readouterr().out.lower()
