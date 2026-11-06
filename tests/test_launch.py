"""Tareas 1 y 2 del plan 001: escáner de fuentes, matching plegado, ejecución detached y contrato de salida."""
from pathlib import Path
from types import SimpleNamespace

import nyx.launch as L

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


def test_parse_kv_normaliza_claves_a_minusculas():
    # ACF real: claves con mayúsculas variables; tras el parseo, siempre minúsculas
    acf = '"appmanifest"\n{\n\t"AppID"\t\t"268500"\n\t"Name"\t\t"XCOM 2"\n}\n'
    assert L.parse_kv(acf) == {"appid": "268500", "name": "XCOM 2"}


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


XCOM_DESKTOP = """[Desktop Entry]
Name=XCOM® 2
Exec=steam steam://rungameid/268500
"""

ACF_XCOM = """"appmanifest"
{
	"appid"		"268500"
	"name"		"XCOM 2"
}
"""


def test_collect_dedupe_por_appid_de_exec(monkeypatch, tmp_path):
    # el atajo .desktop apunta a steam://rungameid/268500: el appmanifest del 268500 sobra,
    # aunque su nombre plegado ("xcom 2") no coincida con el del .desktop ("xcom® 2")
    cands = _scan(monkeypatch, tmp_path, desktops=[("XCOM 2.desktop", XCOM_DESKTOP)],
                  acfs=[("appmanifest_268500.acf", ACF_XCOM)])
    assert [(c.name, c.kind, c.appid) for c in cands] == [("XCOM® 2", "desktop", "268500")]


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
    assert L.main([]) == L.EXIT_ERROR
    assert "--list" in capsys.readouterr().err


# --- Tarea 2: matching ---------------------------------------------------------------

def test_match_exacto_gana_a_subcadena():
    cands = [L.Candidate("Workspace", "workspace", "desktop", desktop_id="workspace"),
             L.Candidate("Notion Workspace", "notion workspace", "desktop", desktop_id="notion")]
    assert [c.name for c in L.match("workspace", cands)] == ["Workspace"]


def test_match_exacto_unico_ignora_parciales():
    cands = [L.Candidate("Project Zomboid", "project zomboid", "desktop", desktop_id="pz"),
             L.Candidate("Project Zomboid Guide", "project zomboid guide", "desktop", desktop_id="guide")]
    assert [c.name for c in L.match("project zomboid", cands)] == ["Project Zomboid"]


def test_match_subcadena_en_name():
    cands = [L.Candidate("Project Zomboid", "project zomboid", "desktop", desktop_id="pz")]
    assert [c.name for c in L.match("zómboid", cands)] == ["Project Zomboid"]  # tildes y mayúsculas da igual


def test_match_ambiguo_orden_determinista():
    c1 = L.Candidate("Total War: WARHAMMER", "total war: warhammer", "steam", appid="364360")
    c2 = L.Candidate("Total War: THREE KINGDOMS", "total war: three kingdoms", "steam", appid="899790")
    r1 = L.match("total war", [c1, c2])
    r2 = L.match("total war", [c2, c1])  # mismo orden aunque las candidatas entren al revés
    assert [c.name for c in r1] == [c.name for c in r2] == ["Total War: THREE KINGDOMS", "Total War: WARHAMMER"]


def test_match_consulta_corta_sin_exacto_vacio():
    cands = [L.Candidate("Project Zomboid", "project zomboid", "desktop", desktop_id="pz")]
    assert L.match("zo", cands) == []
    assert L.match("", cands) == []
    # un exacto corto sí vale: no hay nada que confundir
    corta = L.Candidate("R", "r", "desktop", desktop_id="r")
    assert [c.name for c in L.match("r", [corta])] == ["R"]


def test_match_nombre_de_fichero():
    # "firefox" no está en Name, sí en el nombre del fichero
    cands = [L.Candidate("Navegador web", "navegador web", "desktop", desktop_id="firefox-esr",
                         filefold="firefox-esr")]
    assert [c.name for c in L.match("firefox", cands)] == ["Navegador web"]


def test_match_genericname_y_keywords_menor_peso(monkeypatch, tmp_path):
    cands = _scan(monkeypatch, tmp_path, desktops=[
        ("Kate.desktop", "[Desktop Entry]\nName=Kate Editor\n"),
        ("Otro.desktop", "[Desktop Entry]\nName=Otro\nGenericName=Editor de Kate\n"),
        ("Tercero.desktop", "[Desktop Entry]\nName=Tercero\nKeywords=kate;editor;\n"),
    ])
    r = L.match("kate", cands)
    assert [c.name for c in r] == ["Kate Editor", "Otro", "Tercero"]  # Name (50) por delante de genérico/keywords (25)


def test_match_cubre_name_es(monkeypatch, tmp_path):
    # Name=Files con Name[es]=Archivos: por cualquiera de los dos se encuentra, mismo peso
    cands = _scan(monkeypatch, tmp_path, desktops=[
        ("org.gnome.Files.desktop", "[Desktop Entry]\nName=Files\nName[es]=Archivos\n"),
    ])
    assert [c.alt for c in cands] == ["archivos"]
    assert [c.name for c in L.match("archivos", cands)] == ["Files"]


# --- Tarea 2: entorno y ejecución -----------------------------------------------------

def _pop_capturado(monkeypatch, pops):
    monkeypatch.setattr(L.subprocess, "Popen", lambda *a, **k: (pops.append((a, k)), None)[-1])
    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=""))


def test_launch_env_quita_ld_y_merea_display(monkeypatch):
    fake = SimpleNamespace(stdout="DISPLAY=:0\nWAYLAND_DISPLAY=wayland-1\nXDG_RUNTIME_DIR=/run/user/1000\n")
    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: fake)
    env = L.launch_env({"LD_PRELOAD": "x", "LD_LIBRARY_PATH": "y", "PATH": "/usr/bin"})
    assert "LD_PRELOAD" not in env and "LD_LIBRARY_PATH" not in env
    assert env["DISPLAY"] == ":0" and env["WAYLAND_DISPLAY"] == "wayland-1"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"


def test_launch_env_no_pisa_lo_que_ya_hay(monkeypatch):
    fake = SimpleNamespace(stdout="DISPLAY=:99\n")
    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: fake)
    assert L.launch_env({"DISPLAY": ":0"})["DISPLAY"] == ":0"


def test_launch_env_fallo_de_systemctl_se_ignora(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("sin systemctl")

    monkeypatch.setattr(L.subprocess, "run", boom)
    assert L.launch_env({"DISPLAY": ":0"}) == {"DISPLAY": ":0"}


def test_launch_usa_gtk_launch_o_steam(monkeypatch):
    calls = []
    _pop_capturado(monkeypatch, calls)
    monkeypatch.setattr(L.shutil, "which", lambda b: "/usr/bin/" + b)  # CI sin gtk-launch/steam en PATH
    L.launch(L.Candidate("Project Zomboid", "project zomboid", "desktop", desktop_id="Project Zomboid"))
    L.launch(L.Candidate("XCOM 2", "xcom 2", "steam", appid="268500"))
    assert calls[0][0][0][:2] == ["gtk-launch", "Project Zomboid"]
    assert calls[1][0][0][:2] == ["steam", "steam://rungameid/268500"]
    assert all(k["start_new_session"] for _, k in calls)
    assert all(k["stdin"] is L.subprocess.DEVNULL and k["stdout"] is L.subprocess.DEVNULL
               and k["stderr"] is L.subprocess.DEVNULL for _, k in calls)


# --- Tarea 2: contrato de salida de main ----------------------------------------------

def test_main_unica_candidata_lanza_y_ok(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[("Project Zomboid.desktop", DESKTOP)])
    pops = []
    _pop_capturado(monkeypatch, pops)
    monkeypatch.setattr(L.shutil, "which", lambda b: "/usr/bin/" + b)
    assert L.main(["zomboid"]) == L.EXIT_OK
    assert capsys.readouterr().out == "OK Project Zomboid\n"
    assert pops[0][0][0][:2] == ["gtk-launch", "Project Zomboid"]


def test_main_ambigua_numera_y_no_lanza(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[
        ("total-war-warhammer.desktop", "[Desktop Entry]\nName=Total War: WARHAMMER\n"),
        ("total-war-tres.desktop", "[Desktop Entry]\nName=Total War: THREE KINGDOMS\n"),
    ])
    pops = []
    _pop_capturado(monkeypatch, pops)
    assert L.main(["total war"]) == L.EXIT_AMBIGUOUS
    assert capsys.readouterr().out == "1) Total War: THREE KINGDOMS\n2) Total War: WARHAMMER\n"
    assert not pops


def test_main_no_encontrado_sugerencias(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[("Zomboid.desktop", "[Desktop Entry]\nName=Zomboid\n")])
    assert L.main(["zumboid"]) == L.EXIT_NOT_FOUND
    out = capsys.readouterr().out
    assert "no encuentro nada parecido a «zumboid»" in out
    assert "Zomboid" in out  # sugerencia difflib


def test_main_no_encontrado_maximo_3_sugerencias(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[(f"{n}.desktop", f"[Desktop Entry]\nName={n}\n")
                                           for n in ("Alfa", "Alfa 2", "Alfa 3", "Alfa 4")])
    assert L.main(["alffa"]) == L.EXIT_NOT_FOUND
    out = capsys.readouterr().out
    sugeridas = [n for n in ("Alfa", "Alfa 2", "Alfa 3", "Alfa 4") if n in out]
    assert 1 <= len(sugeridas) <= 3


def test_main_pick_lanza_la_elegida(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[
        ("total-war-warhammer.desktop", "[Desktop Entry]\nName=Total War: WARHAMMER\n"),
        ("total-war-tres.desktop", "[Desktop Entry]\nName=Total War: THREE KINGDOMS\n"),
    ])
    pops = []
    _pop_capturado(monkeypatch, pops)
    monkeypatch.setattr(L.shutil, "which", lambda b: "/usr/bin/" + b)
    assert L.main(["total war", "--pick", "2"]) == L.EXIT_OK
    assert capsys.readouterr().out == "OK Total War: WARHAMMER\n"
    assert pops[0][0][0][:2] == ["gtk-launch", "total-war-warhammer"]  # la segunda de la lista numerada


def test_main_pick_fuera_de_rango(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[("Project Zomboid.desktop", DESKTOP)])
    pops = []
    _pop_capturado(monkeypatch, pops)
    assert L.main(["zomboid", "--pick", "9"]) == L.EXIT_ERROR
    assert "9" in capsys.readouterr().out
    assert not pops


def test_main_binario_ausente_exit_error(monkeypatch, tmp_path, capsys):
    _scan(monkeypatch, tmp_path, desktops=[("Project Zomboid.desktop", DESKTOP)])
    monkeypatch.setattr(L.shutil, "which", lambda b: None)
    assert L.main(["zomboid"]) == L.EXIT_ERROR
    assert "gtk-launch" in capsys.readouterr().out
