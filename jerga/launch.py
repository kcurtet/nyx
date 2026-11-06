"""Escáner de apps instaladas: entradas .desktop del menú XDG y juegos Steam (appmanifests)."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .commands import _fold

EXIT_OK, EXIT_AMBIGUOUS, EXIT_NOT_FOUND, EXIT_ERROR = 0, 3, 4, 5

_USO = 'uso: jerga launch --list [filtro] · jerga launch "nombre"'
_RAIZ_STEAM = Path("~/.steam/steam").expanduser()
_STEAM_ARTEFACTOS = re.compile(r"proton|steam linux runtime|redistributable|voice files", re.I)
_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')
_ACF_PAR = re.compile(r'"([^"]+)"\s+"([^"]*)"')


@dataclass(frozen=True)
class Candidate:
    name: str  # nombre mostrado: Name= o "name" del ACF
    folded: str  # _fold(name), precalculado
    kind: str  # "desktop" | "steam"
    desktop_id: str | None = None  # id para gtk-launch (subdirectorios → guiones)
    appid: str | None = None  # juego Steam
    path: str = ""  # fichero de origen (debug)


def desktop_dirs() -> list[Path]:
    """Directorios <xdg>/applications de usuario y sistema, sin duplicados (usuario primero)."""
    bases = [os.environ.get("XDG_DATA_HOME") or "~/.local/share"]
    bases += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    out, vistos = [], set()
    for base in bases:
        apps = Path(base).expanduser() / "applications"
        if apps.is_dir() and apps not in vistos:
            vistos.add(apps)
            out.append(apps)
    return out


def parse_desktop(text: str) -> dict[str, str]:
    """Claves de [Desktop Entry]; los Desktop Actions nunca entran. Primera aparición gana."""
    out: dict[str, str] = {}
    entry = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            entry = s == "[Desktop Entry]"
            continue
        if not entry or "=" not in s:
            continue
        key, _, value = s.partition("=")
        out.setdefault(key.strip(), value.strip())
    return out


def parse_kv(text: str) -> dict[str, str]:
    """Pares "clave" "valor" de un appmanifest ACF (formato KV de Valve)."""
    out: dict[str, str] = {}
    for key, value in _ACF_PAR.findall(text):
        out.setdefault(key, value)
    return out


def steam_roots() -> list[Path]:
    """Bibliotecas de Steam vía libraryfolders.vdf (ambas ubicaciones); sin Steam, lista vacía."""
    out, vistos = [], set()

    def add(p: Path):
        p = p.expanduser()
        if p.is_dir() and p not in vistos:
            vistos.add(p)
            out.append(p)

    for vdf in (_RAIZ_STEAM / "config" / "libraryfolders.vdf",
                _RAIZ_STEAM / "steamapps" / "libraryfolders.vdf"):
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for path in _VDF_PATH.findall(text):
            add(Path(path))
    if not out:
        add(_RAIZ_STEAM)  # biblioteca por defecto, aunque falte el vdf
    return out


def _verdad(valor: str) -> bool:
    return valor.strip().strip('"').lower() == "true"


def _nombre_visible(datos: dict[str, str]) -> str | None:
    if datos.get("Name"):
        return datos["Name"]
    locales = sorted(k for k in datos if k.startswith("Name["))
    return datos[locales[0]] if locales else None


def _desktop_cands() -> list[Candidate]:
    out, vistos = [], set()
    for d in desktop_dirs():
        for f in sorted(d.glob("**/*.desktop")):
            try:
                datos = parse_desktop(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if _verdad(datos.get("NoDisplay", "")) or _verdad(datos.get("Hidden", "")):
                continue
            nombre = _nombre_visible(datos)
            if not nombre:
                continue
            desktop_id = f.relative_to(d).with_suffix("").as_posix().replace("/", "-")
            if desktop_id in vistos:
                continue
            vistos.add(desktop_id)
            out.append(Candidate(nombre, _fold(nombre), "desktop", desktop_id=desktop_id, path=str(f)))
    return out


def _steam_cands(ya: set[str]) -> list[Candidate]:
    out = []
    for root in steam_roots():
        for f in sorted((root / "steamapps").glob("appmanifest_*.acf")):
            try:
                datos = parse_kv(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            nombre, appid = datos.get("name"), datos.get("appid")
            if not nombre or not appid:
                continue
            if _STEAM_ARTEFACTOS.search(nombre):
                continue
            folded = _fold(nombre)
            if folded in ya:  # mismo juego ya presente como .desktop
                continue
            ya.add(folded)
            out.append(Candidate(nombre, folded, "steam", appid=appid, path=str(f)))
    return out


def collect() -> list[Candidate]:
    """Todas las candidatas, orden determinista (nombre plegado, id)."""
    desktops = _desktop_cands()
    steam = _steam_cands({c.folded for c in desktops})
    return sorted(desktops + steam, key=lambda c: (c.folded, c.desktop_id or c.appid or ""))


def main(argv: list[str]) -> int:
    if sys.platform == "win32":
        print("Todavía no sé abrir apps en Windows.")
        return EXIT_ERROR
    if argv[:1] == ["--list"]:
        filtro = _fold(argv[1]) if len(argv) > 1 else ""
        for c in collect():
            if filtro in c.folded:
                print(c.name)
        return EXIT_OK
    print(_USO, file=sys.stderr)
    return EXIT_ERROR
