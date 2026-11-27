"""«Parar nyx» del tray: sustituye a «Cerrar icono», que mataba el icono sin parar nada.
Mockea which+Popen+notify: nunca ejecuta systemctl ni notify-send reales."""
import nyx.tray as tray


def _mock(monkeypatch, systemctl="/usr/bin/systemctl"):
    """Registra la secuencia de efectos de stop_service (aviso, margen, stop)."""
    hechos = []
    monkeypatch.setattr(tray, "notify", lambda title, body="": hechos.append(("notify", title, body)))
    monkeypatch.setattr(tray.shutil, "which", lambda b: systemctl)
    monkeypatch.setattr(tray.time, "sleep", lambda s: hechos.append(("sleep", s)))
    monkeypatch.setattr(tray.subprocess, "Popen", lambda *a, **k: hechos.append(("stop", a)))
    return hechos


def test_stop_service_avisa_antes_de_parar(monkeypatch):
    # el aviso sale ANTES: el kill del cgroup se comería una notificación posterior
    hechos = _mock(monkeypatch)
    tray.stop_service()
    assert hechos[0][0] == "notify"
    assert "systemctl --user start nyx" in hechos[0][2]  # cómo re-arrancar


def test_stop_service_da_margen_al_aviso_y_para_al_final(monkeypatch):
    hechos = _mock(monkeypatch)
    tray.stop_service()
    assert ("sleep", 0.3) in hechos  # margen para que el aviso llegue a pantalla
    assert hechos[-1] == ("stop", (["systemctl", "--user", "stop", "nyx"],))


def test_stop_service_sin_systemctl_no_hace_nada(monkeypatch):
    hechos = []
    monkeypatch.setattr(tray, "notify", lambda title, body="": hechos.append(title))
    monkeypatch.setattr(tray.shutil, "which", lambda b: None)
    monkeypatch.setattr(tray.subprocess, "Popen", lambda *a, **k: hechos.append(a))
    tray.stop_service()
    assert hechos == []
