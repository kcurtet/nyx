from nyx.postprocess import PostProcessor
from nyx.transcribe import Segment, paragraphs, render, stamp, to_srt


def S(a, b, t, who=None):
    return Segment(a, b, t, who)


def test_stamp():
    assert stamp(5.4) == "00:05"
    assert stamp(3725) == "1:02:05"
    assert stamp(4.25, srt=True) == "00:00:04,250"


def test_parrafos_por_frase_pausa_y_hablante():
    segs = [S(0, 4, "a" * 100 + "."), S(4, 8, "b" * 100 + "."), S(8, 9, "c."), S(15, 16, "tras pausa."),
            S(16, 17, "yo hablo", "Yo"), S(17, 18, "y sigo", "Yo"), S(18, 19, "ellos", "Ellos")]
    ps = [[s.text[:1] for s in p] for p in paragraphs(segs)]
    assert ps == [["a", "b"], ["c"], ["t"], ["y", "y"], ["e"]]


def test_markdown_y_srt():
    segs = [S(0, 2, "Hola.", "Yo"), S(2, 3, "Adiós.", "Ellos")]
    md = render(segs, "md", "reunión", "r.mp4", 3)
    assert md.startswith("# reunión\n")
    assert "`[00:00]` **Yo:** Hola." in md and "`[00:02]` **Ellos:** Adiós." in md
    assert to_srt(segs).startswith("1\n00:00:00,000 --> 00:00:02,000\nYo: Hola.\n")
    assert "no se ha detectado voz" in render([], "md", "x")


def test_extension_pegada():
    fix = PostProcessor({}, {"enabled": False}, []).apply_rules
    assert fix("copia el package .json y el main .py") == "copia el package.json y el main.py"
    assert fix("esto es. Json") == "esto es. Json"


def test_tray_estado_e_icono():
    from nyx.tray import icon_image, state_of

    assert state_of(None) == "down"
    assert state_of({"stt_ready": False}) == "busy"
    assert state_of({"stt_ready": True, "recording": True, "speaking": True}) == "recording"
    assert state_of({"stt_ready": True, "speaking": True}) == "speaking"
    assert state_of({"stt_ready": True}) == "idle"
    img = icon_image("recording", 64)
    assert img.size == (64, 64) and img.getpixel((32, 4))[:3] == (255, 69, 58)


# ---------------------------------------------------------------- sesiones y notas
import time as _time

import numpy as np

from nyx.session import SR, Chunker, NotesWatcher, quiet_cut


def test_quiet_cut_busca_el_silencio():
    a = np.random.default_rng(0).normal(0, 0.3, SR * 10).astype(np.float32)
    a[int(SR * 7.0): int(SR * 7.3)] = 0  # silencio en 7.0-7.3 s
    cut = quiet_cut(a)
    assert SR * 7.0 <= cut <= SR * 7.3


def test_chunker_trozos_con_offset():
    got = []
    c = Chunker(lambda audio, off, who: got.append((audio.size / SR, off, who)), "Yo")
    noise = np.random.default_rng(1).normal(0, 0.2, int(SR * 0.1)).astype(np.float32)
    for _ in range(300):  # 30 s
        c.feed(noise)
    c.flush()
    assert len(got) == 2 and got[0][1] == 0 and got[0][2] == "Yo"
    assert abs(got[1][1] - got[0][0]) < 1e-6  # el 2º empieza donde acabó el 1º
    assert abs(sum(g[0] for g in got) - 30) < 0.01


def test_notas_solo_nuevas_y_estables(tmp_path):
    old = tmp_path / "vieja.ogg"
    old.write_bytes(b"x")
    import os
    os.utime(old, (_time.time() - 3600, _time.time() - 3600))
    nueva_antes = tmp_path / "justo-al-arrancar.ogg"  # mtime unos ms "antes" de arrancar (Windows)
    nueva_antes.write_bytes(b"a")
    os.utime(nueva_antes, (_time.time() - 0.5, _time.time() - 0.5))
    done = []
    w = NotesWatcher([str(tmp_path)], [".ogg"], lambda p: done.append(p.name) or p.with_suffix(".md"))
    nueva = tmp_path / "nueva.ogg"
    nueva.write_bytes(b"audio")
    assert w.step() == [] and done == []          # 1ª pasada: se apunta el tamaño
    assert len(w.step()) == 2 and sorted(done) == ["justo-al-arrancar.ogg", "nueva.ogg"]  # 2ª: estables
    assert w.step() == [] and len(done) == 2      # nunca dos veces; la vieja nunca
    (tmp_path / "otra.mp4").write_bytes(b"v")
    assert w.step() == []                                # extensión no vigilada


def test_silencio_y_alucinaciones():
    from types import SimpleNamespace as NS

    from nyx.transcribe import is_hallucination, transcribe_audio

    class FakeSTT:
        def segments(self, audio):
            return [NS(start=0, end=1, text="Hola.", no_speech_prob=0.1, avg_logprob=-0.2, compression_ratio=1.2),
                    NS(start=1, end=2, text="Esto me hace más protección contra mordiscos.", no_speech_prob=0.8,
                       avg_logprob=-1.1, compression_ratio=1.3)]

    assert transcribe_audio(FakeSTT(), np.zeros(SR * 5, np.float32)) == []  # silencio: ni se intenta
    voz = np.random.default_rng(2).normal(0, 0.1, SR * 2).astype(np.float32)
    assert [s.text for s in transcribe_audio(FakeSTT(), voz)] == ["Hola."]
    assert is_hallucination(NS(no_speech_prob=0.1, avg_logprob=-0.2, compression_ratio=3.0))


def test_ficheros_largos_por_bloques():
    from types import SimpleNamespace as NS

    from nyx.transcribe import blocks, transcribe_long

    rng = np.random.default_rng(3)
    audio = rng.normal(0, 0.1, SR * 60 * 25).astype(np.float32)  # 25 min
    for m in (5, 10, 15, 20):  # silencios cerca de cada frontera de 5 min
        audio[SR * (60 * m - 8): SR * (60 * m - 7)] = 0
    lim = blocks(audio.size, audio, 300)
    assert len(lim) == 5 and lim[0][0] == 0 and lim[-1][1] == audio.size
    assert all(a2 == b1 for (_, b1), (a2, _) in zip(lim, lim[1:], strict=False))  # sin huecos ni solapes
    assert abs(lim[0][1] / SR - (300 - 7.5)) < 0.6  # cortado en el silencio

    calls = []

    class FakeSTT:
        dictation_waiting = False

        def segments(self, a, context=""):
            calls.append(context)
            return [NS(start=0, end=1, text=f"bloque {len(calls)}.", no_speech_prob=0, avg_logprob=0, compression_ratio=1)]

    progress = []
    segs = transcribe_long(FakeSTT(), audio, opts={"long_after_s": 600, "block_s": 300},
                           on_block=lambda s, f: progress.append(round(f, 2)))
    assert [s.text for s in segs] == [f"bloque {i}." for i in range(1, 6)]
    assert calls[0] == "" and calls[1] == "bloque 1." and "bloque 2." in calls[2]  # contexto encadenado
    assert progress[-1] == 1.0 and segs[1].start == lim[1][0] / SR

    corto = rng.normal(0, 0.1, SR * 60).astype(np.float32)
    calls.clear()
    transcribe_long(FakeSTT(), corto, opts={"long_after_s": 600})
    assert calls == [""]  # corto: entero, una sola llamada


def test_seleccion_por_copia(monkeypatch):
    import nyx.output as o

    class Clip:
        has_primary = True

        def __init__(self):
            self.data, self.prim, self.sets = b"portapapeles viejo", b"seleccion vieja", []

        def get(self, primary=False):
            return self.prim if primary else self.data

        def set(self, d, primary=False):
            self.sets.append(d)
            self.data = d

    class Keys:
        def __init__(self, clip, copies):
            self.clip, self.copies, self.pressed = clip, copies, []

        def combo(self, c):
            self.pressed.append(c)
            if self.copies:
                self.clip.data = b"texto seleccionado ahora"

    monkeypatch.setattr(o.time, "sleep", lambda s: None)
    out = o.Output.__new__(o.Output)
    out.clip = Clip()
    out.keys = Keys(out.clip, copies=True)
    assert out.selection() == "texto seleccionado ahora"
    # Linux: nunca Ctrl+C (mataría procesos en terminales). Windows: Ctrl+C (Windows Terminal copia si hay selección)
    copy_key = "ctrl+c" if o.IS_WINDOWS else "ctrl+insert"
    assert out.keys.pressed == [copy_key]

    out.clip = Clip()
    out.keys = Keys(out.clip, copies=False)  # la app no copió → selección primaria
    assert out.selection() == "seleccion vieja"
    assert out.selection("primary") == "seleccion vieja" and out.keys.pressed == [copy_key]


def test_consola_utf8(monkeypatch):
    import io
    import sys

    from nyx.app import _utf8_console

    raw = io.BytesIO()
    fake = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", fake)
    _utf8_console()
    print("✔ ✘ · —")
    fake.flush()
    assert raw.getvalue().decode("utf-8").startswith("✔ ✘ · —")
