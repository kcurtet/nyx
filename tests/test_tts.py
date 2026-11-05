from jerga.config import DEFAULTS
from jerga.hotkey import parse_combo
from jerga.tts import Lexicon, normalize, prepare, sentences

LEX = Lexicon(DEFAULTS["tts"]["lexicon"])


def say(t):
    return " ".join(prepare(t, LEX))


def test_lexicon_terminos_y_articulos():
    assert say("Haz un git push.") == "Haz un guit push."
    assert say("El CI/CD falla.") == "La integración continua falla."
    assert say("El pipeline del CI/CD falla.") == "El paip-láin de la integración continua falla."
    assert say("Mira el YAML con kubectl.") == "Mira el yámal con kiub ci ti el."
    assert say("Levanta el docker compose.") == "Levanta el dóker, compóus."


def test_lexicon_no_rompe_palabras():
    assert say("Abre GitHub y el .gitignore") == "Abre GitHub y el .gitignore"


def test_codigo_y_markdown():
    md = "## Resumen\n\nHe cambiado **dos** cosas:\n\n- el `Dockerfile`\n- el [README](https://x.y)\n\n```python\nprint('hola')\n```\nListo."
    out = normalize(md)
    assert "Resumen" in out and "**" not in out and "`" not in out and "#" not in out
    assert "Bloque de código en python." in out and "print" not in out
    assert "el Dockerfile" in out and "el README" in out


def test_urls_rutas_emojis_tablas():
    assert normalize("Mira https://github.com/kcurtet/jerga/issues/3 ahora") == "Mira un enlace a github.com ahora"
    assert normalize("Edita /etc/udev/rules.d/80-jerga.rules ya") == "Edita 80-jerga.rules ya"
    assert normalize("Abre ~/dev/jerga/README.md") == "Abre README.md"
    assert normalize("Listo 🚀✅") == "Listo"
    assert normalize("| a | b |\n|---|---|\n| 1 | 2 |\nFin.") == "Hay una tabla.\nFin."


def test_sentences():
    parts = sentences("Hola. Vale. Esta es una frase bastante más larga que las otras dos anteriores, sin duda.")
    assert parts[0] == "Hola. Vale."
    assert all(len(p) <= 220 for p in sentences("palabra " * 200))


def test_parse_combo():
    assert parse_combo("ctrl+;") == (["ctrl"], "KEY_SEMICOLON")
    assert parse_combo("ctrl+KEY_SEMICOLON") == (["ctrl"], "KEY_SEMICOLON")
    assert parse_combo("ctrl+alt+r") == (["ctrl", "alt"], "KEY_R")
    assert parse_combo("KEY_F9") == ([], "KEY_F9")
