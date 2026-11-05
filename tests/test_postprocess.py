from jerga.postprocess import PostProcessor, apply_voice_commands

CMD = {"question_words": ["pregunta"], "spanish_open_question": True}


def q(text, **kw):
    return apply_voice_commands(text, {**CMD, **kw})


def test_pregunta_al_final():
    assert q("Has hecho el push a main pregunta.") == "¿Has hecho el push a main?"
    assert q("has hecho el push a main, pregunta") == "¿Has hecho el push a main?"
    assert q("¿Has hecho el push, pregunta?") == "¿Has hecho el push?"


def test_mayusculas_y_sin_apertura():
    assert q("funciona el build Pregunta.") == "¿Funciona el build?"
    assert q("funciona el build pregunta", spanish_open_question=False) == "funciona el build?"


def test_no_toca_si_no_esta_al_final():
    assert q("Tengo una pregunta sobre Docker.") == "Tengo una pregunta sobre Docker."
    assert q("preguntale a Juan") == "preguntale a Juan"
    assert q("Pregunta.") == "Pregunta."


def test_sin_palabras_configuradas():
    assert apply_voice_commands("vale pregunta", {}) == "vale pregunta"


def test_integrado_con_reemplazos():
    p = PostProcessor({"hit push": "git push"}, {"enabled": False}, [], CMD)
    assert p("Has hecho el hit push pregunta.") == "¿Has hecho el git push?"
