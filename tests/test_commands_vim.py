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
