"""Output.press: secuencias de teclas token a token (spec 007, D1/D6). Fakes siempre."""


class FakeKeys:  # como UInputKeys/PynputKeys, pero registra los combos
    PRESS_CAPABLE = True

    def __init__(self, fail_first=None):
        self.combos = []
        self.fail_first = fail_first

    def combo(self, combo):
        if combo == self.fail_first:  # falla UNA vez y sigue
            self.fail_first = None
            raise RuntimeError("boom")
        self.combos.append(combo)


class PartialKeys:  # como ydotool/wtype/xdotool: no cubre el set de teclas
    def __init__(self):
        self.combos = []

    def combo(self, combo):
        self.combos.append(combo)


class FakeClip:
    def __init__(self):
        self.calls = []

    def get(self, primary=False):
        self.calls.append(("get", primary))
        return b""

    def set(self, data, primary=False):
        self.calls.append(("set", primary))


def out_with(keys, clip=None):
    """Output sin tocar el entorno (ni pick_clipboard ni pick_keys)."""
    from nyx.output import Output

    out = Output.__new__(Output)
    out.cfg = {}
    out.clip = clip
    out.keys = keys
    return out


def test_press_ejecuta_tokens_en_orden():
    k = FakeKeys()
    out_with(k).press(["esc", "d", "d"])
    assert k.combos == ["esc", "d", "d"]  # un token = una pulsación atómica


def test_press_sin_capa_de_teclas():
    out_with(None).press(["esc", "d"])  # method clipboard o sin uinput: no-op, sin excepción


def test_press_token_que_falla_sigue():
    k = FakeKeys(fail_first="d")
    out_with(k).press(["esc", "d", "d"])
    assert k.combos == ["esc", "d"]  # el fallo se logea, la secuencia continúa


def test_press_capa_parcial_es_noop():  # D6: ydotool/wtype/xdotool no cubren el set
    k = PartialKeys()
    out_with(k).press(["esc", "d"])
    assert k.combos == []


def test_press_no_toca_portapapeles():  # C2: pegar mecánica intacta, cero clipboard
    clip = FakeClip()
    k = FakeKeys()
    out_with(k, clip).press(["esc", "d"])
    assert k.combos == ["esc", "d"]
    assert clip.calls == []


def test_c2_parse_produce_keys_y_press_los_ejecuta():  # C2 unit: parse → press con fake
    from nyx.commands import parse
    from nyx.config import DEFAULTS

    r = parse("modo vim borrar línea", DEFAULTS["commands"])
    assert r.keys == ["esc", "d", "d"] and r.discard and not r.text
    k = FakeKeys()
    out_with(k).press(r.keys)
    assert k.combos == ["esc", "d", "d"]


def test_app_comprueba_keys_antes_de_discard():  # C2: la rama keys ANTES que discard (si no, muerta)
    from pathlib import Path

    import nyx.app

    src = Path(nyx.app.__file__).read_text()
    assert src.index("if res.keys:") < src.index("if res.discard:")


def test_pynput_alias_de_simbolos(monkeypatch):
    """pynput.keyboard.Key no tiene semicolon/dot/slash (son chars vía KeyCode) ni pageup/pagedown
    (se llaman page_up/page_down): _k debe resolverlos o los mapeos vim con colon/slash fallan (D6)."""
    import sys
    import types

    kb = types.ModuleType("pynput.keyboard")

    class Key:  # fiel al enum real: sin semicolon/dot/slash/pageup/pagedown
        enter = "enter"
        esc = "esc"
        insert = "insert"
        page_up = "page_up"
        page_down = "page_down"

    kb.Controller = lambda: None
    kb.Key = Key
    fake = types.ModuleType("pynput")
    fake.keyboard = kb
    monkeypatch.setitem(sys.modules, "pynput", fake)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", kb)

    from nyx.output import PynputKeys

    pk = PynputKeys()
    assert pk._k("semicolon") == ";"
    assert pk._k("dot") == "."
    assert pk._k("slash") == "/"
    assert pk._k("pageup") == "page_up"
    assert pk._k("pagedown") == "page_down"
