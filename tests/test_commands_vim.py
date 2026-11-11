"""«vim»: frases → secuencias de teclas (Result.keys), gramática léxica y vim_layout (spec 007)."""
from nyx.commands import parse
from nyx.config import DEFAULTS

CMD = DEFAULTS["commands"]


def p(text, **kw):
    return parse(text, {**CMD, **kw})


def test_vim_borrar_linea():  # A1
    r = p("modo vim borrar línea")
    assert r.keys == ["esc", "d", "d"]
    assert (r.text, r.discard) == ("", True)


def test_vim_guardar_por_layout():  # A2: colon resuelto según vim_layout
    assert p("modo vim guardar", vim_layout="us").keys == \
        ["esc", "shift+semicolon", "w", "enter"]
    assert p("modo vim guardar", vim_layout="es").keys == \
        ["esc", "shift+dot", "w", "enter"]


def test_vim_buscar():  # A3: slash lógico → tecla física según layout
    assert p("modo vim buscar", vim_layout="us").keys == ["esc", "slash"]
    assert p("modo vim buscar", vim_layout="es").keys == ["esc", "shift+7"]


def test_vim_rehacer():  # A6: combo
    assert p("modo vim rehacer").keys == ["esc", "ctrl+r"]


def test_vim_fuera_de_mapa_o_solo():  # A4: se escribe tal cual, cero teclas
    r = p("vim salta")
    assert (r.text, r.keys, r.discard) == ("vim salta", None, False)
    r = p("vim")
    assert (r.text, r.keys, r.discard) == ("vim", None, False)


def test_vim_dos_palabras_prefijo():  # «vim …» y «modo vim …» ambos valen
    assert p("vim deshacer").keys == ["esc", "u"]
    assert p("modo vim deshacer").keys == ["esc", "u"]


def test_vim_cuerpo_con_extras_no_matchea():  # mapa exacto, como toda frase-orden
    r = p("vim borrar línea ya")
    assert (r.text, r.keys) == ("vim borrar línea ya", None)


def test_vim_mayusculas_y_tildes():  # matching plegado
    assert p("MODO VIM BORRAR LÍNEA.").keys == ["esc", "d", "d"]


def test_vim_en_medio_de_frase_no_hace_nada():  # es comando de prefijo
    r = p("El modo vim es mejor")
    assert (r.text, r.keys) == ("El modo vim es mejor", None)


def test_vim_mapa_usuario_gana():  # A5: redefinir un mapeo (y valida en la gramática)
    cmd = {**CMD, "vim_map": {**CMD["vim_map"], "insertar al final": "esc shift+s"}}
    assert parse("modo vim insertar al final", cmd).keys == ["esc", "shift+s"]


def test_vim_token_ilegal():  # A7: mapeo ignorado con log, frase tal cual
    cmd = {**CMD, "vim_map": {**CMD["vim_map"], "volar": "esc volar"}}
    r = parse("modo vim volar", cmd)
    assert (r.text, r.keys) == ("modo vim volar", None)


def test_vim_porcent_y_exclamacion_universales():  # trampa del check: % → shift+5, ! → shift+1
    assert p("modo vim buscar y reemplazar").keys == \
        ["esc", "shift+semicolon", "shift+5", "s", "slash"]
    assert p("modo vim forzar salir").keys == \
        ["esc", "shift+semicolon", "q", "shift+1", "enter"]


def test_vim_set_inicial_del_mapa():  # D-A3: ~20 mapeos, TODOS empiezan con esc
    assert len(CMD["vim_map"]) >= 20
    assert all(seq.split()[0] == "esc" for seq in CMD["vim_map"].values())


def test_vim_no_interfiere_con_codigo_y_ruta():  # orden de prefijos: código → ruta → vim
    assert p("código git status").text == "`git status`"
    assert p("código modo vim guardar").text == "`modo vim guardar`"
    assert p("ruta tilde barra dev").text == "~/dev"


# ------------------------------------------- «programar»: código de una línea (spec 007)
def test_programar_linea_completa():  # B1
    r = p("modo programar const a es igual a entre comillas hello world cierra comillas punto y coma")
    assert (r.text, r.send, r.discard, r.keys) == ('const a = "hello world";', False, False, None)


def test_programar_con_numeros():  # B2: números del mapa, palabras tal cual
    assert p("programar si x mayor que tres devuelve verdadero").text == "si x > 3 devuelve verdadero"


def test_programar_comilla_abierta():  # B3: toggle explícito, no adivina el cierre
    assert p("programar const a es igual a entre comillas hola punto y coma").text == 'const a = "hola;'


def test_programar_fold():  # B4: matching plegado, grafía original conservada
    assert p("PROGRAMAR Guión Bajo x").text == "_x"


def test_prioridad_codigo_y_ruta():  # B5: gana el primero (código → ruta → vim → programar)
    assert p("código git status").text == "`git status`"
    assert p("ruta tilde barra dev").text == "~/dev"
    assert p("código programar x").text == "`programar x`"
    r = p("ruta programar x")  # «ruta» gana: se pega como path sin espacios
    assert r.text == "programarx"


def test_programar_sin_cuerpo():  # B6
    r = p("modo programar")
    assert (r.text, r.send, r.discard) == ("modo programar", False, False)


def test_programar_dos_puntos_gana_a_dos():  # B7: multi-palabra primero
    assert p("programar dos puntos").text == ":"
    assert p("programar x guion bajo dos").text == "x_2"  # y el número pega al guion bajo


def test_programar_exento_de_inline():  # D3: «punto y aparte» dentro NO mete salto
    r = p("programar x punto y aparte y")
    assert "\n" not in r.text
    assert r.text == "x. y aparte y"


def test_programar_exento_de_lowercase_prev():  # D3: retorno temprano
    assert p("programar Hola en minúsculas").text == "Hola en minúsculas"


def test_programar_sufijo_entre_comillas_al_final():  # trampa documentada (heredada de «ruta»)
    # El sufijo quote_words se pela ANTES del prefijo y desactiva programar: NO se arregla.
    assert p("programar di entre comillas").text == '"programar di"'


def test_programar_encadena_con_envia():  # el sufijo envía sobrevive al retorno temprano
    r = p("programar x es igual a tres envía")
    assert (r.text, r.send) == ("x = 3", True)


def test_programar_operadores_y_pegados():
    assert p("programar x mayor o igual veinte").text == "x >= 20"  # clave de la spec: sin «que»
    assert p("programar a más b por c").text == "a + b * c"
    # paréntesis NO en v1: la palabra pasa tal cual
    assert p("programar f abra paréntesis x").text == "f abra paréntesis x"


def test_programar_en_config_por_defecto():
    assert DEFAULTS["commands"]["code_line_words"] == ["programar", "modo programar"]


def test_vocabulario_cubre_los_mapas():  # D4: las palabras nuevas en el vocabulary default
    from nyx.commands import _CODE_SYMBOLS, _fold

    vocab = {_fold(w) for w in DEFAULTS["stt"]["vocabulary"]}
    assert {_fold(w) for w in CMD["vim_map"]} <= vocab
    assert {_fold(w) for w in _CODE_SYMBOLS} <= vocab
    assert {_fold(w) for w in CMD["vim_words"] + CMD["code_line_words"]} <= vocab


def test_vim_variantes_foneticas_whisper():  # en español, «vim» se oye /bim/ → bim/beam
    assert p("modo bim borrar línea").keys == ["esc", "d", "d"]
    assert p("Modo Beam, insertar").keys == ["esc", "i"]
    assert p("bim guardar y salir").keys == ["esc", "shift+semicolon", "w", "q", "enter"]
