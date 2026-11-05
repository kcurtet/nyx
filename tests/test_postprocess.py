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
