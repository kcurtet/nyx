"""Migración de rutas jerga→nyx (spec 003, D2).

Todo bajo un home temporal inyectado: la migración JAMÁS se prueba contra las
rutas reales del usuario.
"""
from pathlib import Path

from nyx import migrate

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

CONFIG_TOML = '''# configuración de jerga de prueba
[stt]
model = "small"  # valor que no se toca

[orders]
wake_words = ["trinity"]
agent = "trinity"
debug = false

[record]
dir = "/home/kx/Documentos/jerga"

[notes]
dirs = ["/home/kx/Documentos/jerga/notas"]
'''


def _home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


def _plantar_jerga(h: Path) -> None:
    """Instalación vieja con datos dentro: config, estado y notas."""
    cfg = h / ".config" / "jerga"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text(CONFIG_TOML, encoding="utf-8")
    st = h / ".local" / "state" / "jerga"
    (st / "trinity-sessions").mkdir(parents=True)
    (st / "trinity-sessions" / "sesion-1.json").write_text("{}", encoding="utf-8")
    (st / "trinity-pi.log").write_text("pi", encoding="utf-8")
    (st / "jerga.log").write_text("log", encoding="utf-8")
    notas = h / "Documents" / "jerga" / "notas"
    notas.mkdir(parents=True)
    (notas / "nota.ogg").write_bytes(b"audio")


def test_migracion_completa(tmp_path):
    h = _home(tmp_path)
    _plantar_jerga(h)

    msgs = migrate.run(home=h)

    assert len(msgs) == 4  # config movida + config.toml reescrito + estado + notas
    assert msgs[1].startswith("config.toml")
    # config: renombrada, backup del original intacto y valores reescritos
    assert not (h / ".config" / "jerga").exists()
    new_cfg = h / ".config" / "nyx"
    assert (new_cfg / "config.toml.pre-nyx").read_text(encoding="utf-8") == CONFIG_TOML
    with open(new_cfg / "config.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["orders"]["wake_words"] == ["nyx"]
    assert data["orders"]["agent"] == "nyx-agent"
    assert data["record"]["dir"] == "/home/kx/Documentos/nyx"
    assert data["notes"]["dirs"] == ["/home/kx/Documentos/nyx/notas"]
    assert data["stt"]["model"] == "small"  # lo demás, intacto
    # estado: renombrado, con las piezas de trinity/jerga dentro
    assert not (h / ".local" / "state" / "jerga").exists()
    st = h / ".local" / "state" / "nyx"
    assert (st / "nyx-agent-sessions" / "sesion-1.json").read_text(encoding="utf-8") == "{}"
    assert (st / "nyx-agent-pi.log").read_text(encoding="utf-8") == "pi"
    assert (st / "nyx.log").read_text(encoding="utf-8") == "log"
    # notas: renombradas con los datos dentro
    assert not (h / "Documents" / "jerga").exists()
    assert (h / "Documents" / "nyx" / "notas" / "nota.ogg").read_bytes() == b"audio"


def test_segunda_pasada_no_toca_nada(tmp_path):
    h = _home(tmp_path)
    _plantar_jerga(h)
    migrate.run(home=h)
    huella = sorted(str(p.relative_to(h)) for p in h.rglob("*"))

    assert migrate.run(home=h) == []
    assert sorted(str(p.relative_to(h)) for p in h.rglob("*")) == huella


def test_vieja_y_nueva_a_la_vez_gana_la_nueva(tmp_path):
    h = _home(tmp_path)
    _plantar_jerga(h)
    # el usuario ya probó nyx antes de migrar: config, estado y notas nuevos
    (h / ".config" / "nyx").mkdir(parents=True)
    (h / ".config" / "nyx" / "config.toml").write_text('[ui]\nbackend = "tk"\n', encoding="utf-8")
    (h / ".local" / "state" / "nyx").mkdir(parents=True)
    (h / "Documents" / "nyx").mkdir(parents=True)  # todo convive

    msgs = migrate.run(home=h)

    assert len(msgs) == 3
    assert msgs[0].startswith("config") and "no se toca" in msgs[0]
    assert msgs[1].startswith("estado") and msgs[2].startswith("notas")
    # la vieja sigue viva y la nueva manda: nada se borra ni se reescribe
    assert (h / ".config" / "jerga" / "config.toml").exists()
    assert (h / ".config" / "jerga" / "config.toml").read_text(encoding="utf-8") == CONFIG_TOML
    assert (h / ".config" / "nyx" / "config.toml").read_text(encoding="utf-8") == '[ui]\nbackend = "tk"\n'
    assert (h / ".local" / "state" / "jerga" / "jerga.log").exists()
    assert (h / "Documents" / "jerga" / "notas" / "nota.ogg").exists()


def test_sin_nada_que_migrar(tmp_path):
    assert migrate.run(home=_home(tmp_path)) == []


def test_wake_trini_y_otras_palabras(tmp_path):
    h = _home(tmp_path)
    cfg = h / ".config" / "jerga"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text(
        '[orders]\nwake_words = ["trini", "jefe"]\nagent = "trini"\n', encoding="utf-8")

    msgs = migrate.run(home=h)

    assert len(msgs) == 2  # el directorio y la reescritura del config.toml
    with open(h / ".config" / "nyx" / "config.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["orders"]["wake_words"] == ["nyx", "jefe"]  # las otras palabras sobreviven
    assert data["orders"]["agent"] == "nyx-agent"


def test_config_vacia_se_migra_igual(tmp_path):
    """Caso límite de la spec: dir viejo sin config.toml — migrar es barato y uniforme."""
    h = _home(tmp_path)
    (h / ".config" / "jerga").mkdir(parents=True)

    msgs = migrate.run(home=h)

    assert len(msgs) == 1
    assert (h / ".config" / "nyx").is_dir()
    assert not (h / ".config" / "nyx" / "config.toml").exists()
    assert not (h / ".config" / "nyx" / "config.toml.pre-nyx").exists()  # sin backup de nada


def test_solo_hay_notas(tmp_path):
    h = _home(tmp_path)
    (h / "Documents" / "jerga").mkdir(parents=True)

    msgs = migrate.run(home=h)

    assert len(msgs) == 1 and msgs[0].startswith("notas")
    assert (h / "Documents" / "nyx").is_dir()


def test_rutas_de_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(migrate.config, "IS_WINDOWS", True)
    h = _home(tmp_path)
    (h / "AppData" / "Roaming" / "jerga").mkdir(parents=True)
    (h / "AppData" / "Roaming" / "jerga" / "config.toml").write_text(
        '[orders]\nwake_words = ["trinity"]\n', encoding="utf-8")
    (h / "AppData" / "Local" / "jerga").mkdir(parents=True)
    (h / "AppData" / "Local" / "jerga" / "trinity-pi.log").write_text("pi", encoding="utf-8")

    msgs = migrate.run(home=h)

    assert len(msgs) == 3  # config movida + config.toml reescrito + estado
    with open(h / "AppData" / "Roaming" / "nyx" / "config.toml", "rb") as f:
        assert tomllib.load(f)["orders"]["wake_words"] == ["nyx"]
    assert (h / "AppData" / "Local" / "nyx" / "nyx-agent-pi.log").exists()


def test_error_de_movimiento_avisa_sin_perder_nada(monkeypatch, tmp_path):
    h = _home(tmp_path)
    _plantar_jerga(h)

    def denegado(src, dst):
        raise OSError("permiso denegado")

    monkeypatch.setattr(migrate.shutil, "move", denegado)
    msgs = migrate.run(home=h)

    assert len(msgs) == 3 and all("no pude" in m for m in msgs)
    assert (h / ".config" / "jerga" / "config.toml").exists()  # nada perdido
    assert (h / ".local" / "state" / "jerga" / "jerga.log").exists()
    assert (h / "Documents" / "jerga" / "notas" / "nota.ogg").exists()


def test_fallo_al_reescribir_config_no_rompe_nada(monkeypatch, tmp_path):
    h = _home(tmp_path)
    _plantar_jerga(h)

    def boom(path):
        raise OSError("solo lectura")

    monkeypatch.setattr(migrate, "_rewrite_config", boom)
    msgs = migrate.run(home=h)

    assert any("no pude reescribirlo" in m for m in msgs)
    assert (h / ".config" / "nyx" / "config.toml").read_text(encoding="utf-8") == CONFIG_TOML
    assert (h / ".config" / "nyx" / "config.toml.pre-nyx").exists()  # backup a pesar de todo


def test_la_migracion_real_nunca_toca_el_home_del_runner():
    """Sin home inyectado, los pares apuntan a ~/.config|state y Documentos, no a tmp."""
    for label, old, new in migrate._pairs(None):
        assert label in ("config", "estado", "notas")
        assert "jerga" in old.name and new.name == "nyx"
        assert old.parent == new.parent
