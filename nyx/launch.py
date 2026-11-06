"""Escáner de apps instaladas, matching plegado y arranque detached (.desktop vía gtk-launch, Steam vía appid)."""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .commands import _fold

EXIT_OK, EXIT_AMBIGUOUS, EXIT_NOT_FOUND, EXIT_ERROR = 0, 3, 4, 5

_USO = 'uso: nyx launch "nombre" [--pick N] · nyx launch --list [filtro]'
_RAIZ_STEAM = Path("~/.steam/steam").expanduser()
_STEAM_ARTEFACTOS = re.compile(r"proton|steam linux runtime|redistributable|voice files", re.I)
_SESSION_KEYS = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY")
_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')
_ACF_PAR = re.compile(r'"([^"]+)"\s+"([^"]*)"')
_RUNGAMEID = re.compile(r"steam://rungameid/(\d+)")


@dataclass(frozen=True)
class Candidate:
    name: str  # nombre mostrado: Name= o "name" del ACF
    folded: str  # _fold(name), precalculado
    kind: str  # "desktop" | "steam"
    desktop_id: str | None = None  # id para gtk-launch (subdirectorios → guiones)
    appid: str | None = None  # juego Steam (del ACF o del steam://rungameid/ del Exec)
    filefold: str = ""  # _fold del nombre de fichero (desktop_id o stem del ACF), precalculado
    generic: str = ""  # _fold(GenericName=), precalculado
    keywords: str = ""  # _fold(Keywords=), precalculado
    alt: str = ""  # _fold(Name[es]=) si difiere del principal, precalculado

    def sort_key(self) -> tuple[str, str]:
        """Orden determinista compartido por collect() y match(): (nombre plegado, id)."""
        return (self.folded, self.desktop_id or self.appid or "")


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
    """Pares "clave" "valor" de un appmanifest ACF (formato KV de Valve); claves normalizadas a minúsculas."""
    out: dict[str, str] = {}
    for key, value in _ACF_PAR.findall(text):
        out.setdefault(key.lower(), value)
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
            alt = _fold(datos.get("Name[es]", ""))
            rungame = _RUNGAMEID.search(datos.get("Exec", ""))
            out.append(Candidate(nombre, _fold(nombre), "desktop", desktop_id=desktop_id,
                                 appid=rungame.group(1) if rungame else None,
                                 filefold=_fold(desktop_id), generic=_fold(datos.get("GenericName", "")),
                                 keywords=_fold(datos.get("Keywords", "")),
                                 alt=alt if alt != _fold(nombre) else ""))
    return out


def _steam_cands(ya: set[str], ya_appids: set[str]) -> list[Candidate]:
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
            if folded in ya or appid in ya_appids:  # juego ya presente como .desktop
                continue
            ya.add(folded)
            ya_appids.add(appid)
            out.append(Candidate(nombre, folded, "steam", appid=appid,
                                 filefold=_fold(f.stem)))
    return out


def collect() -> list[Candidate]:
    """Todas las candidatas, orden determinista (nombre plegado, id)."""
    desktops = _desktop_cands()
    steam = _steam_cands({c.folded for c in desktops}, {c.appid for c in desktops if c.appid})
    return sorted(desktops + steam, key=Candidate.sort_key)


def _score(q: str, c: Candidate) -> int:
    """Puntos de una candidata: exacto 100, Name o Name[es] 50, fichero 40, genérico/keywords 25."""
    if q == c.folded:
        return 100
    if len(q) < 3:  # subcadenas cortas matchean media biblioteca
        return 0
    if q in c.folded or q in c.alt:
        return 50
    if q in c.filefold:
        return 40
    if q in c.generic or q in c.keywords:
        return 25
    return 0


def match(query: str, cands: list[Candidate]) -> list[Candidate]:
    """Candidatas que matchean la consulta, ordenadas y deterministas (-score, plegado, id)."""
    q = _fold(query).strip()
    if not q:
        return []
    scored = [(c, s) for c in cands if (s := _score(q, c))]
    exactos = [c for c, s in scored if s == 100]
    if len(exactos) == 1:  # un exacto único gana a todos los parciales
        return exactos
    scored.sort(key=lambda par: (-par[1], *par[0].sort_key()))
    return [c for c, _ in scored]


def launch_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Copia env (u os.environ) sin los LD de CUDA de nyx; claves de sesión ausentes, del session manager."""
    out = dict(os.environ if env is None else env)
    out.pop("LD_PRELOAD", None)
    out.pop("LD_LIBRARY_PATH", None)
    faltan = [k for k in _SESSION_KEYS if not out.get(k)]
    if not faltan:
        return out
    try:
        res = subprocess.run(["systemctl", "--user", "show-environment"],
                             capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):  # sin systemctl o colgado: seguimos con lo que hay
        return out
    for line in res.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in faltan:
            out[key] = value
    return out


class _BinarioAusente(Exception):
    """El lanzador (gtk-launch, steam) no está en PATH."""


def launch(cand: Candidate, env: dict[str, str] | None = None) -> None:
    """Arranca la candidata detached: gtk-launch para .desktop, steam:// para juegos de Steam."""
    if cand.kind == "steam":
        cmd = ["steam", f"steam://rungameid/{cand.appid}"]
    else:
        cmd = ["gtk-launch", cand.desktop_id or ""]
    if shutil.which(cmd[0]) is None:
        raise _BinarioAusente(cmd[0])
    subprocess.Popen(cmd, env=launch_env(env), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    args, pick = argv[:], None
    if "--pick" in args:
        i = args.index("--pick")
        if i + 1 >= len(args) or not args[i + 1].isdigit():
            print(_USO, file=sys.stderr)
            return EXIT_ERROR
        pick = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    if not args:
        print(_USO, file=sys.stderr)
        return EXIT_ERROR
    query = " ".join(args)
    todas = collect()
    cands = match(query, todas)
    if not cands:
        por_folded = {c.folded: c.name for c in todas}
        cercanas = difflib.get_close_matches(_fold(query), por_folded, n=3)
        print(f"no encuentro nada parecido a «{query}»")
        if cercanas:
            print("¿Quisiste decir: " + ", ".join(por_folded[f] for f in cercanas) + "?")
        return EXIT_NOT_FOUND
    if pick is not None:
        if not 1 <= pick <= len(cands):  # el orden es determinista: el índice re-resuelve igual
            print(f"no hay candidata número {pick}")
            return EXIT_ERROR
        elegida = cands[pick - 1]
    elif len(cands) > 1:
        for i, c in enumerate(cands, 1):
            print(f"{i}) {c.name}")
        return EXIT_AMBIGUOUS
    else:
        elegida = cands[0]
    try:
        launch(elegida)
    except _BinarioAusente as e:
        print(f"no puedo lanzar: {e} no está en PATH")
        return EXIT_ERROR
    print(f"OK {elegida.name}")
    return EXIT_OK
