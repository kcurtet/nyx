from jerga.postprocess import PostProcessor
from jerga.transcribe import Segment, paragraphs, render, stamp, to_srt


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
