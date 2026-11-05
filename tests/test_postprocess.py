from jerga.config import DEFAULTS
from jerga.postprocess import PostProcessor, apply_voice_commands

CMD = DEFAULTS["commands"]


def c(text, **kw):
    return apply_voice_commands(text, {**CMD, **kw})


def test_interrogante():
    assert c("Has hecho el push a main interrogante.") == "¿Has hecho el push a main?"
    assert c("has hecho el push a main, interrogante") == "¿Has hecho el push a main?"
    assert c("¿Has hecho el push, interrogante?") == "¿Has hecho el push?"
    assert c("funciona el build signo de interrogación") == "¿Funciona el build?"


def test_exclamacion_con_y_sin_tilde():
    assert c("Ya pasa el build exclamación.") == "¡Ya pasa el build!"
    assert c("ya pasa el build exclamacion") == "¡Ya pasa el build!"
    assert c("ya pasa el build, punto de exclamación.") == "¡Ya pasa el build!"
    assert c("Ya pasa el build Exclamación") == "¡Ya pasa el build!"


def test_sin_signo_de_apertura():
    assert c("funciona interrogante", spanish_open_marks=False) == "funciona?"


def test_compatibilidad_config_antigua():
    old = {"question_words": ["pregunta"], "spanish_open_question": False}
    assert apply_voice_commands("funciona pregunta", old) == "funciona?"


def test_no_toca_si_no_esta_al_final():
    assert c("Tengo una pregunta sobre Docker.") == "Tengo una pregunta sobre Docker."
    assert c("Tengo una pregunta.") == "Tengo una pregunta."
    assert c("El interrogante es si escala.") == "El interrogante es si escala."
    assert c("Interrogante.") == "Interrogante."


def test_integrado_con_reemplazos():
    p = PostProcessor({"hit push": "git push"}, {"enabled": False}, [], CMD)
    assert p("Has hecho el hit push interrogante.") == "¿Has hecho el git push?"


# ---------------------------------------------------------------- comandos nuevos
from jerga.commands import parse  # noqa: E402


def p(text):
    return parse(text, CMD)


def test_envia():
    r = p("Revisa el endpoint de la API. Envía.")
    assert (r.text, r.send) == ("Revisa el endpoint de la API.", True)
    r = p("vale, envía")
    assert (r.text, r.send) == ("vale", True)


def test_encadenados():
    r = p("Has hecho el push interrogante, envía.")
    assert (r.text, r.send) == ("¿Has hecho el push?", True)
    r = p("código git status envía")
    assert (r.text, r.send) == ("`git status`", True)


def test_borra_eso():
    assert p("Esto no era lo que quería, borra eso.").discard
    assert p("vale bórralo").discard
    assert not p("Borra eso del fichero de config.").discard  # no está al final


def test_codigo():
    assert p("Código git push origin main.").text == "`git push origin main`"
    assert p("Abre el código fuente.").text == "Abre el código fuente."  # no está al principio


def test_comillas_y_minusculas():
    assert p("Hola mundo, entre comillas.").text == '"Hola mundo"'
    assert p("Feature login con OAuth en minúsculas.").text == "feature login con OAuth"


def test_nueva_linea_y_punto_y_aparte():
    assert p("Primera línea, nueva línea, segunda línea.").text == "Primera línea\nsegunda línea."
    assert p("Hecho el deploy punto y aparte. ahora los tests.").text == "Hecho el deploy.\nAhora los tests."


def test_palabra_sola_no_hace_nada():
    for w in ("Envía.", "Borra eso.", "Interrogante.", "Código."):
        r = p(w)
        assert (r.text, r.send, r.discard) == (w, False, False)
