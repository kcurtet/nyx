"""Doctor: issues #8 y #9 — el check de voz mentía (✔ con el TTS caído: solo hacía
`import ptts`) y el check de servicio veía «no está en marcha» justo tras un restart
(systemd da la unidad por activa antes de que el socket acepte pings)."""
import sys
import types

import pytest

import nyx.doctor as doc
import nyx.hotkey as hotkey

VOZ = {"tts": {"enabled": True, "voice": "Nerea", "key": "ctrl+0"}}


@pytest.fixture()
def _sin_audio(monkeypatch):
    """El check de salida de audio toca hardware: fuera de los tests de voz."""
    monkeypatch.setattr(doc, "_doctor_salida_audio", lambda r: None)


class _R:  # Report sin pintar: registra líneas para asertar
    def __init__(self):
        self.lineas = []

    def section(self, title):
        pass

    def ok(self, what, detail=""):
        self.lineas.append(("ok", what, detail))

    def warn(self, what, detail=""):
        self.lineas.append(("warn", what, detail))

    def bad(self, what, detail=""):
        self.lineas.append(("bad", what, detail))


def _reloj_falso(monkeypatch):
    """Monotonic+sleep coordinados: los reintentos de arranque avanzan sin esperar."""
    ahora = [0.0]
    monkeypatch.setattr(doc.time, "monotonic", lambda: ahora[0])
    monkeypatch.setattr(doc.time, "sleep", lambda s: ahora.__setitem__(0, ahora[0] + s))


# --- #9: esperar a que el socket acepte pings tras el restart -------------------------
def test_status_espera_el_arranque_del_socket(monkeypatch):
    _reloj_falso(monkeypatch)
    respuestas = [False, False]  # restart: la unidad activa, el socket aún no
    monkeypatch.setattr(hotkey, "is_running", lambda: respuestas.pop(0) if respuestas else True)
    monkeypatch.setattr(hotkey, "send_command", lambda cmd: '{"version": "9.9"}')
    st = doc._status_con_arranque(_R())
    assert st == {"version": "9.9"}


def test_status_declara_caida_solo_tras_la_espera(monkeypatch):
    _reloj_falso(monkeypatch)
    monkeypatch.setattr(hotkey, "is_running", lambda: False)
    r = _R()
    assert doc._status_con_arranque(r, settle=2.0) is None
    assert ("warn", "no está en marcha", "systemctl --user start nyx  (o ejecuta `nyx`)") in r.lineas


def test_status_viva_sin_status_no_miente(monkeypatch):
    _reloj_falso(monkeypatch)
    monkeypatch.setattr(hotkey, "is_running", lambda: True)
    monkeypatch.setattr(hotkey, "send_command", lambda cmd: (_ for _ in ()).throw(ValueError("feo")))
    r = _R()
    assert doc._status_con_arranque(r) == {}  # viva: dict vacío, no None
    assert ("ok", "en marcha", "") in r.lineas


# --- #8: el veredicto de la voz lo da quien intentó cargarla --------------------------
@pytest.mark.usefixtures("_sin_audio")
def test_voz_ok_con_tts_ready_del_servicio():
    r = _R()
    doc._doctor_voz(r, VOZ, {"tts_ready": True})
    assert r.lineas == [("ok", "voz phonon · Nerea · tecla ctrl+0 (o «léeme esto»)", "")]


@pytest.mark.usefixtures("_sin_audio")
def test_voz_caida_reporta_el_error_real_del_log(monkeypatch, tmp_path):
    log = tmp_path / "nyx.log"
    log.write_text("01:00 [tts] phonon listo · voz Nerea\n"
                   "01:01 [tts] no disponible: cannot fetch config.json (GatedRepo)\n", encoding="utf-8")
    monkeypatch.setattr(doc.config, "LOG_PATH", log)
    r = _R()
    doc._doctor_voz(r, VOZ, {"tts_ready": False})
    what, detail = r.lineas[0][1], r.lineas[0][2]
    assert r.lineas[0][0] == "bad" and what == "la voz no carga"
    assert "GatedRepo" in detail and str(log) in detail


@pytest.mark.usefixtures("_sin_audio")
def test_voz_sin_servicio_no_da_veredicto_falso():
    r = _R()
    doc._doctor_voz(r, VOZ, None)
    assert r.lineas[0][0] == "warn" and "no comprobado" in r.lineas[0][2]


@pytest.mark.usefixtures("_sin_audio")
def test_voz_cargando_no_es_fallo_ni_log_viejo(monkeypatch, tmp_path):
    # cargar tarda ~8 s: un doctor lanzado en ese hueco no debe decir «no carga»
    # con una línea vieja del log como detalle
    log = tmp_path / "nyx.log"
    log.write_text("01:51 [tts] no disponible: GatedRepo (línea vieja)\n", encoding="utf-8")
    monkeypatch.setattr(doc.config, "LOG_PATH", log)
    r = _R()
    doc._doctor_voz(r, VOZ, {"tts_ready": False, "tts_loading": True})
    estado, detalle = r.lineas[0][0], r.lineas[0][2]
    assert estado == "warn" and "cargando" in detalle
    assert "GatedRepo" not in detalle


@pytest.mark.usefixtures("_sin_audio")
def test_voz_en_gpu_libre_esta_descargada_no_caida():
    # el modo GPU libre baja la voz a propósito (y ready queda a False): no es fallo
    r = _R()
    doc._doctor_voz(r, VOZ, {"tts_ready": False, "gpu_free": True, "tts_loading": True})
    assert r.lineas[0][0] == "warn" and "GPU libre" in r.lineas[0][2]


@pytest.mark.usefixtures("_sin_audio")
def test_voz_ptts_no_instalado(monkeypatch):
    monkeypatch.setitem(sys.modules, "ptts", None)  # import ptts → ImportError
    r = _R()
    doc._doctor_voz(r, VOZ, {"tts_ready": True})
    assert r.lineas[0][:2] == ("bad", "ptts no instalado")


def test_voz_desactivada_en_config():
    r = _R()
    doc._doctor_voz(r, {"tts": {"enabled": False}}, {"tts_ready": True})
    assert r.lineas[0][:2] == ("warn", "desactivado")


# --- salida de audio (el resto de la sección, sin tocar hardware) ---------------------
def test_salida_audio_ok(monkeypatch):
    fake = types.ModuleType("sounddevice")
    fake.query_devices = lambda kind: {"name": "default"}
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    r = _R()
    doc._doctor_salida_audio(r)
    assert r.lineas == [("ok", "salida de audio: default", "")]


def test_salida_audio_no_disponible(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)  # import → ImportError
    r = _R()
    doc._doctor_salida_audio(r)
    assert r.lineas[0][:2] == ("warn", "sin salida de audio")
