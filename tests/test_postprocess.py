from nyx.config import DEFAULTS
from nyx.postprocess import PostProcessor, apply_voice_commands

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
from nyx.commands import parse  # noqa: E402


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


# ------------------------------------------------------- «ruta»: paths con símbolos hablados (004)
RCMD = {**CMD, "path_words": ["ruta"]}


def rp(text):
    return parse(text, RCMD)


def test_ruta_simbolos():  # A1, A2
    assert rp("ruta tilde barra dev barra música").text == "~/dev/música"
    assert rp("ruta docs barra specs punto md").text == "docs/specs.md"
    assert rp("ruta tilde barra dev barra jerga punto md.").text == "~/dev/jerga.md"  # punto final de Whisper


def test_ruta_pela_comas_de_whisper():  # Whisper añade comas al pausar: no van al path
    assert rp("ruta barra home, barra vigia").text == "/home/vigia"
    assert rp("ruta docs barra specs, punto md,").text == "docs/specs.md"


def test_ruta_espacio_real():  # A3
    assert rp("ruta mi espacio proyecto").text == "mi proyecto"


def test_ruta_doble_punto_no_es_simbolo():  # A4: «doble punto» NO está en el mapa, va palabra a palabra
    assert rp("ruta doble punto barra barra docs").text == "doble.//docs"
    assert rp("ruta punto punto barra docs").text == "../docs"  # así se escribe ../ en v1


def test_ruta_mayusculas_y_tildes():  # A5: matching plegado, palabras no-símbolo conservan su grafía
    assert rp("RUTA Guión Bajo barra X").text == "_/X"


def test_ruta_contrabarra_y_variantes():
    assert rp("ruta contrabarra Windows barra System32").text == "\\Windows/System32"
    assert rp("ruta barra invertida etc").text == "\\etc"
    assert rp("ruta user arroba host dos puntos 8080").text == "user@host:8080"


def test_ruta_palabra_sola():  # A6: comportamiento estándar, se escribe tal cual
    r = rp("Ruta.")
    assert (r.text, r.send, r.discard) == ("Ruta.", False, False)


def test_ruta_no_interfiere_con_codigo():  # A7 + caso límite: «código ruta …» gana código
    assert rp("código git status").text == "`git status`"
    assert rp("Código ruta tilde barra dev").text == "`ruta tilde barra dev`"


def test_ruta_en_medio_de_frase_no_hace_nada():  # caso límite: es comando de prefijo
    assert rp("La ruta del archivo es larga.").text == "La ruta del archivo es larga."


def test_ruta_encadena_con_envia():
    r = rp("ruta tilde barra dev envía")
    assert (r.text, r.send) == ("~/dev", True)


def test_ruta_en_config_por_defecto():  # D3: el mapa y el comando en el vocabulario de [stt]
    assert DEFAULTS["commands"]["path_words"] == ["ruta"]
    assert {"ruta", "tilde", "barra", "contrabarra", "barra invertida", "punto", "guion",
            "guion bajo", "bajo", "dos puntos", "espacio", "arroba"} <= set(DEFAULTS["stt"]["vocabulary"])


def test_comillas_y_minusculas():
    assert p("Hola mundo, entre comillas.").text == '"Hola mundo"'
    # inline: minusculiza la palabra ANTERIOR al comando
    assert p("Feature login con OAuth en minúsculas.").text == "Feature login con oauth"
    assert p("pon commit KX minúsculas").text == "pon commit kx"
    assert p("el Hub en minúsculas de GitHub").text == "el hub de GitHub"
    assert p("en minúsculas").text == "en minúsculas"  # sin palabra previa: se escribe tal cual


def test_nueva_linea_y_punto_y_aparte():
    assert p("Primera línea, nueva línea, segunda línea.").text == "Primera línea\nsegunda línea."
    assert p("Hecho el deploy punto y aparte. ahora los tests.").text == "Hecho el deploy.\nAhora los tests."


def test_palabra_sola_no_hace_nada():
    for w in ("Envía.", "Borra eso.", "Interrogante.", "Código."):
        r = p(w)
        assert (r.text, r.send, r.discard) == (w, False, False)


# ---------------------------------------------------------------- órdenes
from nyx.orders import match_wake  # noqa: E402

W = DEFAULTS["orders"]["wake_words"]


def test_palabra_de_activacion():
    assert match_wake("Nyx, ve al repo nyx y cambia la imagen.", W) == "Ve al repo nyx y cambia la imagen."
    assert match_wake("nyx ¿qué hace el agente de screeps?", W) == "¿qué hace el agente de screeps?"
    assert match_wake("Oye, Nyx: sí, hazlo.", W) == "Sí, hazlo."
    assert match_wake("Nyx.", W) == ""


def test_no_es_orden():
    assert match_wake("Trinity, ve al repo nyx.", W) is None  # la vieja ya no despierta (spec 003, A4)
    assert match_wake("La Trinity de Matrix era la mejor.", W) is None
    assert match_wake("Trinitys del mundo.", W) is None
    assert match_wake("El nexus del mal.", W) is None  # palabra completa: «nexus» no es «nyx»
    assert match_wake("Haz un git push.", W) is None


def test_pi_args_orquestadora(tmp_path, monkeypatch):
    from nyx.orders import AGENT_DIR, pi_args_for

    agent = tmp_path / "agent"
    (agent / "extensions").mkdir(parents=True)
    (agent / "extensions" / "herdr-agent-state.ts").write_text("//")
    pkg = tmp_path / "pi-herdr"
    pkg.mkdir()
    (pkg / "index.ts").write_text("//")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    args = pi_args_for({"isolated": True, "pi_herdr": str(pkg), "model": "x/y"})
    assert args[:2] == ["--no-extensions", "--no-skills"]
    assert ["-e", str(agent / "extensions" / "herdr-agent-state.ts")] == args[4:6]
    assert ["-e", str(pkg / "index.ts")] == args[6:8]
    assert args[-4:] == ["-e", str(AGENT_DIR / "voice.ts"), "--model", "x/y"]
    assert pi_args_for({"isolated": False}) == ["--skill", str(AGENT_DIR), "-e", str(AGENT_DIR / "voice.ts")]


def test_frases_orden_leer_y_callar():
    for t in ("Léeme esto.", "lee esto", "Léelo", "¿Lee la selección?"):
        assert p(t).action == "read", t
    for t in ("Calla.", "Cállate", "silencio", "Para de leer."):
        assert p(t).action == "hush", t
    # dentro de un dictado normal NO son órdenes
    assert p("Léeme esto despacio que no lo entiendo.").action is None
    assert p("El silencio del log es raro.").action is None


def test_ctrl_con_swapcaps(monkeypatch):
    import pytest

    pytest.importorskip("evdev")  # solo Linux
    import nyx.hotkey as hk

    assert hk.ctrl_key_names(["ctrl:swapcaps"]) == {"KEY_RIGHTCTRL", "KEY_CAPSLOCK"}
    assert hk.ctrl_key_names(["ctrl:nocaps"]) == {"KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_CAPSLOCK"}
    assert hk.ctrl_key_names([]) == {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"}
    assert "KEY_F13" in hk.ctrl_key_names([], ["KEY_F13"])

    monkeypatch.setattr(hk, "xkb_options", lambda: ["ctrl:swapcaps"])
    fired = []
    ptt = hk.PushToTalk("hold", lambda: None, lambda: None, lambda: None)
    L = hk.EvdevListener("KEY_RIGHTCTRL", ptt, [("ctrl+0", lambda: fired.append("leer"))])
    import time
    for code, down in [(58, True), (11, True), (11, False), (58, False)]:  # Bloq Mayús (=Ctrl) + 0
        L._key(code, down)
    time.sleep(0.1)
    assert fired == ["leer"]
