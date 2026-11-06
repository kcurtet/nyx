"""Tarea 1 del plan 001: escáner de fuentes (.desktop + appmanifests) y `jerga launch --list`."""
from pathlib import Path

import jerga.launch as L

DESKTOP = """[Desktop Entry]
Type=Application
Name=Project Zomboid
Name[es]=Project Zomboid
Exec=loquesea
"""

ACF_ZOMBOID = """"appmanifest"
{
	"appid"		"108600"
	"name"		"Project Zomboid"
}
"""

ACF_PROTON = """"appmanifest"
{
	"appid"		"2373500"
	"name"		"Proton 9.0 (Beta)"
}
"""

ACF_RUNTIME = """"appmanifest"
{
	"appid"		"1070560"
	"name"		"Steam Linux Runtime 1.0 (compatible)"
}
"""


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _scan(monkeypatch, tmp_path, desktops=(), acfs=()) -> list[L.Candidate]:
    """Monta apps/ y una biblioteca Steam/ falsas y devuelve collect() sobre ellas."""
    apps, steam = tmp_path / "apps", tmp_path / "steam"
    for rel, text in desktops:
        _write(apps / rel, text)
    for nombre, text in acfs:
        _write(steam / "steamapps" / nombre, text)
    monkeypatch.setattr(L, "desktop_dirs", lambda: [apps])
    monkeypatch.setattr(L, "steam_roots", lambda: [steam])
    return L.collect()


def test_parse_desktop_solo_desktop_entry():
    text = DESKTOP + "\n[Desktop Action Store]\nName=Store\n"
    d = L.parse_desktop(text)
    assert d["Name"] == "Project Zomboid"
    assert "Store" not in d.values()


def test_parse_desktop_primera_aparicion_de_cada_clave():
    d = L.parse_desktop("[Desktop Entry]\nName=Uno\nName=Dos\n")
    assert d["Name"] == "Uno"


def test_desktop_id_con_subdirectorio(monkeypatch, tmp_path):
    cands = _scan(monkeypatch, tmp_path, desktops=[("sub/Kate.desktop", "[Desktop Entry]\nName=Kate\n")])
    assert [c.desktop_id for c in cands] == ["sub-Kate"]


def test_parse_kv_pares_clave_valor():
    assert L.parse_kv(ACF_ZOMBOID) == {"appid": "108600", "name": "Project Zomboid"}


def test_collect_acf_sin_desktop_aparece(monkeypatch, tmp_path):
    cands = _scan(monkeypatch, tmp_path, acfs=[("appmanifest_108600.acf", ACF_ZOMBOID)])
    assert [(c.name, c.kind, c.appid) for c in cands] == [("Project Zomboid", "steam", "108600")]


def test_collect_filtra_artefactos_de_steam(monkeypatch, tmp_path):
    cands = _scan(monkeypatch, tmp_path, acfs=[("appmanifest_2373500.acf", ACF_PROTON),
                                               ("appmanifest_1070560.acf", ACF_RUNTIME)])
    assert cands == []


def test_collect_acf_sin_appid_o_sin_name_fuera(monkeypatch, tmp_path):
    cands = _scan(monkeypatch, tmp_path, acfs=[("appmanifest_a.acf", '"name"\t\t"Solo nombre"\n'),
                                               ("appmanifest_b.acf", '"appid"\t\t"99"\n')])
    assert cands == []


def test_collect_nodisplay_y_hidden_fuera(monkeypatch, tmp_path):
    cands = _scan(monkeypatch, tmp_path, desktops=[
        ("Oculto.desktop", "[Desktop Entry]\nName=Oculto\nNoDisplay=true\n"),
        ("Escondido.desktop", "[Desktop Entry]\nName=Escondido\nHidden=TRUE\n"),
        ("Visible.desktop", "[Desktop Entry]\nName=Visible\n"),
    ])
    assert [c.name for c in cands] == ["Visible"]


def test_collect_mismo_desktop_id_gana_el_primero(monkeypatch, tmp_path):
    _write(tmp_path / "usuario" / "apps" / "Kate.desktop", "[Desktop Entry]\nName=Kate (mía)\n")
    _write(tmp_path / "sistema" / "apps" / "Kate.desktop", "[Desktop Entry]\nName=Kate (sistema)\n")
    monkeypatch.setattr(L, "desktop_dirs", lambda: [tmp_path / "usuario" / "apps", tmp_path / "sistema" / "apps"])
    monkeypatch.setattr(L, "steam_roots", lambda: [])
    cands = L.collect()
    assert [c.name for c in cands] == ["Kate (mía)"]


def test_collect_juego_en_dos_fuentes_no_se_duplica(monkeypatch, tmp_path):
    cands = _scan(monkeypatch, tmp_path, desktops=[("Project Zomboid.desktop", DESKTOP)],
                  acfs=[("appmanifest_108600.acf", ACF_ZOMBOID)])
    assert len(cands) == 1
    assert cands[0].kind == "desktop"


def test_collect_sin_name_usa_name_locale(monkeypatch, tmp_path):
    cands = _scan(monkeypatch, tmp_path, desktops=[
        ("Kate.desktop", "[Desktop Entry]\nName[es]=Catalina\nExec=x\n"),
    ])
    assert [c.name for c in cands] == ["Catalina"]


def test_main_list_imprime_nombres(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[("Project Zomboid.desktop", DESKTOP)])
    assert L.main(["--list"]) == L.EXIT_OK
    assert "Project Zomboid" in capsys.readouterr().out.splitlines()


def test_main_list_filtro_plegado(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[("Project Zomboid.desktop", DESKTOP)],
          acfs=[("appmanifest_108600.acf", ACF_ZOMBOID)])
    assert L.main(["--list", "zómb"]) == L.EXIT_OK  # tildes y mayúsculas da igual
    assert capsys.readouterr().out == "Project Zomboid\n"


def test_main_stub_windows(monkeypatch, capsys):
    monkeypatch.setattr(L.sys, "platform", "win32")
    assert L.main([]) == L.EXIT_ERROR
    assert "windows" in capsys.readouterr().out.lower()


def test_main_sin_argumentos_es_uso(capsys):
    assert L.main(["steam"]) == L.EXIT_ERROR  # el matching llega en la Tarea 2
    assert "--list" in capsys.readouterr().err
