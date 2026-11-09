"""Modo GPU libre (spec 006): unload/self-healing de Transcriber y Speaker, comando "gpu", tray.

Siempre con fakes: `Transcriber._load` y `Speaker.load` (o un módulo ptts falso) se
monkeypatchean — la suite nunca importa faster_whisper ni ptts de verdad.
"""
import sys
import threading
import time
import types

import numpy as np
import pytest

import nyx.stt as o_stt
import nyx.tts as o_tts

# ---------------------------------------------------------------- fakes stt
CFG = {"model": "m", "device": "cpu", "compute_type": "int8", "language": "es",
       "beam_size": 1, "vocabulary": []}


class _Seg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def transcribe(self, audio, **kw):
        return [_Seg(" hola")], None


def _stt(monkeypatch, lenta=False):
    """Transcriber con _load falso: cuenta llamadas y (si `lenta`) espera a `box["out"]`."""
    monkeypatch.setattr(o_stt, "cuda_available", lambda: False)
    box = {"calls": 0, "in": threading.Event(), "out": threading.Event()}
    if not lenta:
        box["out"].set()

    def _load(self, device):
        box["calls"] += 1
        box["in"].set()
        box["out"].wait(5)
        self.model, self.device = _FakeModel(), device

    monkeypatch.setattr(o_stt.Transcriber, "_load", _load)
    return o_stt.Transcriber(CFG), box


# ---------------------------------------------------------------- T1: Transcriber
def test_unload_suelta_y_es_idempotente(monkeypatch):  # A8
    t, box = _stt(monkeypatch)
    t.load()
    assert t.model is not None and t.ready.is_set()
    t.unload()
    assert t.model is None and t.device is None and t.error is None and not t.ready.is_set()
    t.unload()  # segunda llamada: no-op
    assert t.model is None and not t.ready.is_set()
    assert box["calls"] == 1  # unload no recarga


def test_transcribe_selfheal_descargado(monkeypatch):  # A8: model None + error None → carga y espera
    t, box = _stt(monkeypatch)
    assert t.model is None
    assert t.transcribe(np.zeros(16000, np.float32)) == "hola"
    assert box["calls"] == 1  # disparó exactamente una carga


def test_segments_selfheal_descargado(monkeypatch):  # A8: sesiones y ficheros pasan por aquí
    t, box = _stt(monkeypatch)
    assert [s.text for s in t.segments(np.zeros(16000, np.float32))] == [" hola"]
    assert box["calls"] == 1


def test_transcribe_raise_si_error_de_carga(monkeypatch):  # fallo de carga: como hoy, sin self-heal
    t, box = _stt(monkeypatch)
    t.error, _ = RuntimeError("sin modelo"), t.ready.set()
    with pytest.raises(RuntimeError):
        t.transcribe(np.zeros(1600, np.float32))
    with pytest.raises(RuntimeError):
        t.segments(np.zeros(1600, np.float32))
    assert box["calls"] == 0  # con error no se reintenta solo


def test_load_y_unload_se_serializan(monkeypatch):  # A10: nunca queda modelo con el modo libre
    t, box = _stt(monkeypatch, lenta=True)
    seen = []
    tl = threading.Thread(target=t.load)
    tl.start()
    box["in"].wait(5)
    assert t.lock.locked()  # load() tiene la llave DURANTE TODA la carga
    tu = threading.Thread(target=lambda: (t.unload(), seen.append(t.model is None)))
    tu.start()
    time.sleep(0.2)
    assert seen == []  # unload espera: no descarga bajo la carga en marcha
    box["out"].set()
    tl.join(5)
    tu.join(5)
    assert seen == [True] and t.model is None and not t.ready.is_set()  # cargó y luego descargó


def test_guard_sin_doble_carga(monkeypatch):  # A8: dos load() en marcha → una sola _load
    t, box = _stt(monkeypatch, lenta=True)
    ts = [threading.Thread(target=t.load) for _ in range(2)]
    for x in ts:
        x.start()
    box["in"].wait(5)
    time.sleep(0.2)
    assert box["calls"] == 1  # la 2ª load() volvió por el guard
    box["out"].set()
    for x in ts:
        x.join(5)
    assert box["calls"] == 1 and t.model is not None
    t.load()  # ya cargado: también return temprano
    assert box["calls"] == 1


def test_on_loaded_se_llama_tras_exito(monkeypatch):  # y NO tras carga fallida
    t, _box = _stt(monkeypatch)
    hits = []
    t.on_loaded = lambda: hits.append(1)
    t.load()
    assert hits == [1]
    t.unload()

    def roto(self, device):
        raise RuntimeError("roto")

    monkeypatch.setattr(o_stt.Transcriber, "_load", roto)
    with pytest.raises(RuntimeError):
        t.load()
    assert hits == [1] and t.error is not None


# ---------------------------------------------------------------- T2: Speaker
TTS_CFG = {"model": "m", "quant": False, "voice": "es", "lexicon": {}}


class _FakeTTS:
    def __init__(self, **kw):
        self.sample_rate = 16000

    def stream(self, part):
        return iter([np.zeros(4, np.float32)])


def _speaker(monkeypatch, ok=True):
    """Speaker con load() falso a nivel de instancia: asigna tts (o no) y pone ready."""
    sp = o_tts.Speaker(TTS_CFG)

    def load():
        if ok:
            sp.tts = _FakeTTS()
        sp.ready.set()

    monkeypatch.setattr(sp, "load", load)
    return sp


def _ptts_falso(monkeypatch, cls):
    mod = types.ModuleType("ptts")
    mod.TTS = cls
    monkeypatch.setitem(sys.modules, "ptts", mod)


def test_speaker_unload_idempotente(monkeypatch):  # A8
    sp = _speaker(monkeypatch)
    sp.load()
    assert sp.tts is not None and sp.ready.is_set()
    sp.unload()
    assert sp.tts is None and not sp.ready.is_set()
    sp.unload()  # segunda llamada: no-op
    assert sp.tts is None


def test_say_con_tts_descargado_recarga_y_lee(monkeypatch):  # A8: self-heal en say
    sp = _speaker(monkeypatch)
    sp.load()
    sp.unload()
    said, done = [], threading.Event()

    def _run(parts, on_start, on_end):
        said.extend(parts)
        done.set()

    monkeypatch.setattr(sp, "_run", _run)
    assert sp.say("Hola mundo.") is True  # recargó solo y habló: ni hang ni False
    assert done.wait(5) and said == ["Hola mundo."]


def test_say_sigue_fallando_limpio_si_carga_falla(monkeypatch):  # A3: aviso, no hang
    sp = _speaker(monkeypatch, ok=False)
    sp.ready.set()  # carga inicial fallida
    assert sp.say("algo") is False  # reintenta en bg, pero devuelve False rápido
    assert sp.tts is None


def test_speaker_on_loaded_tras_exito(monkeypatch):  # y NO tras carga fallida (load real, ptts falso)
    _ptts_falso(monkeypatch, _FakeTTS)
    sp = o_tts.Speaker(TTS_CFG)
    hits = []
    sp.on_loaded = lambda: hits.append(1)
    sp.load()
    assert sp.tts is not None and hits == [1]
    sp.unload()
    hits.clear()

    class _Roto:
        def __init__(self, **kw):
            raise RuntimeError("roto")

    _ptts_falso(monkeypatch, _Roto)
    sp.load()
    assert sp.tts is None and hits == [] and sp.ready.is_set()  # fallo: sin on_loaded, sin hang


def test_speaker_guard_sin_doble_carga(monkeypatch):  # una sola construcción aunque llamen dos
    box = {"inits": 0, "in": threading.Event(), "out": threading.Event()}

    class _Lenta:
        def __init__(self, **kw):
            box["inits"] += 1
            box["in"].set()
            box["out"].wait(5)
            self.sample_rate = 16000

        def stream(self, s):
            return iter([np.zeros(4, np.float32)])

    _ptts_falso(monkeypatch, _Lenta)
    sp = o_tts.Speaker(TTS_CFG)
    ts = [threading.Thread(target=sp.load) for _ in range(2)]
    for x in ts:
        x.start()
    box["in"].wait(5)
    time.sleep(0.2)
    assert box["inits"] == 1  # la 2ª load() volvió por el guard
    box["out"].set()
    for x in ts:
        x.join(5)
    assert box["inits"] == 1 and sp.tts is not None
