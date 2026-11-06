"""Migración de las rutas de jerga a las de nyx (spec 003, D2): una sola vez, una sola copia viva.

Al primer arranque renombra los directorios viejos a los nuevos (Windows espejo con
%APPDATA%/%LOCALAPPDATA%):

    ~/.config/jerga        → ~/.config/nyx
    ~/.local/state/jerga   → ~/.local/state/nyx
    ~/Documentos/jerga     → ~/Documentos/nyx

Del config.toml se deja copia de seguridad (config.toml.pre-nyx) porque se reescriben
valores conocidos; dentro del estado se renombran trinity-sessions→nyx-sessions,
trinity-pi.log→nyx-pi.log y jerga.log→nyx.log. Idempotente: sin ruta vieja no hace
nada; si vieja y nueva conviven (el usuario ya probó nyx), gana la nueva y la vieja
no se toca (se avisa). Un directorio viejo vacío se migra igual: es barato y uniforme.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from . import config

# Lo que se renombra DENTRO del directorio de estado una vez movido.
_STATE_RENAMES = (("trinity-sessions", "nyx-sessions"), ("trinity-pi.log", "nyx-pi.log"),
                  ("jerga.log", "nyx.log"))


def run(home: Path | None = None) -> list[str]:
    """Migra las rutas viejas y devuelve un mensaje por cada cosa hecha (para log y doctor).

    `home` inyecta la base de TODAS las rutas (los tests lo hacen con tmp_path):
    con él no se mira el entorno. Sin él, las rutas reales del usuario (XDG_* /
    APPDATA, igual que config.py).
    """
    msgs: list[str] = []
    for label, old, new in _pairs(home):
        msgs += _migrate(label, old, new)
    return msgs


def _pairs(home: Path | None) -> list[tuple[str, Path, Path]]:
    h = home if home is not None else Path.home()
    if config.IS_WINDOWS:
        cfg = _root("APPDATA", h / "AppData" / "Roaming", home)
        state = _root("LOCALAPPDATA", h / "AppData" / "Local", home)
    else:
        cfg = _root("XDG_CONFIG_HOME", h / ".config", home)
        state = _root("XDG_STATE_HOME", h / ".local" / "state", home)
    docs = h / "Documents" if home is not None else config.docs_root()
    return [("config", cfg / "jerga", cfg / "nyx"),
            ("estado", state / "jerga", state / "nyx"),
            ("notas", docs / "jerga", docs / "nyx")]


def _root(env: str, fallback: Path, home: Path | None) -> Path:
    if home is not None:  # home inyectado: aislado del entorno del runner
        return fallback
    v = os.environ.get(env)
    return Path(v) if v else fallback


def _migrate(label: str, old: Path, new: Path) -> list[str]:
    if not old.exists():
        return []
    if new.exists():  # el usuario ya probó nyx antes de migrar: gana la nueva
        return [f"{label}: conviven {old} y {new}; se usa la nueva y la vieja no se toca"]
    backup = ""
    if label == "config" and (old / "config.toml").exists():
        shutil.copy2(old / "config.toml", old / "config.toml.pre-nyx")
        backup = " (backup: config.toml.pre-nyx)"
    try:
        shutil.move(str(old), str(new))  # rename en el mismo disco; copia si cambia
    except OSError as e:
        return [f"{label}: no pude mover {old} → {new} ({e}); nada se ha perdido"]
    if label == "config":
        try:
            rewritten = _rewrite_config(new / "config.toml")
        except (OSError, UnicodeError) as e:  # nunca romper el arranque por esto
            return [f"{label}: {old} → {new}{backup}",
                    f"config.toml: no pude reescribirlo ({e}); está intacto con los valores viejos"]
        if rewritten:
            return [f"{label}: {old} → {new}{backup}",
                    "config.toml: wake/agent trinity→nyx, rutas con jerga→nyx"]
    if label == "estado":
        for src, dst in _STATE_RENAMES:
            s, d = new / src, new / dst
            if s.exists() and not d.exists():
                try:
                    s.rename(d)
                except OSError:
                    pass  # queda con el nombre viejo: se recreará vacío, sin perder datos
    return [f"{label}: {old} → {new}{backup}"]


# ------------------------------------------------------------------ config.toml
def _rewrite_config(path: Path) -> bool:
    """Reescribe valores conocidos del config.toml migrado. Devuelve si cambió algo."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    new = _rewrite_toml(text)
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def _rewrite_toml(text: str) -> str:
    """Toque quirúrgico línea a línea (conserva comentarios y formato del usuario).

    Solo [orders] wake_words/agent (trinity|trini → nyx, el resto de palabras
    sobrevive; tener «trinity» y «trini» a la vez dejaría "nyx" repetida, que es
    inofensiva) y las claves de rutas [record] dir / [notes] dirs (jerga → nyx).
    """
    out: list[str] = []
    section = key = ""
    depth = 0  # arrays a várias líneas: las líneas de dentro heredan la clave abierta
    for line in text.splitlines(keepends=True):
        if depth <= 0:
            head = re.match(r"\s*\[([^\]]+)\]", line)
            kv = re.match(r"\s*([A-Za-z0-9_-]+)\s*=", line)
            if head and not kv:
                section, key = head.group(1).strip(), ""
            elif kv:
                key = kv.group(1)
        line = _rewrite_line(section, key, line) if key else line
        depth = max(0, depth + line.count("[") - line.count("]"))
        out.append(line)
    return "".join(out)


def _rewrite_line(section: str, key: str, line: str) -> str:
    if section == "orders" and key in ("wake_words", "agent"):
        return re.sub(r"""(?i)(["'])(trinity|trini)\1""", r"\1nyx\1", line)
    if (section, key) in (("record", "dir"), ("notes", "dirs")):
        return re.sub(r"""(["'])([^"']*)\1""",
                      lambda m: f"{m[1]}{m[2].replace('jerga', 'nyx')}{m[1]}", line)
    return line
