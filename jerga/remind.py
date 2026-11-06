"""Recordatorios one-shot: systemd-run crea un timer que dispara notify-send (respaldo visual) + jerga say (voz)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

from .hotkey import is_running

EXIT_OK, EXIT_ERROR = 0, 5

_USO = 'uso: jerga remind "texto" en <cuándo> · jerga remind --list · jerga remind --cancel N'
_PREFIJO = "jerga remind: "  # la Description de la unidad lleva el texto: --list lo recupera de ahí
_REL = re.compile(r"^(\d+)\s*(s|seg(?:undos?)?|m|min(?:utos?)?|h|horas?)$")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_NUMERO = re.compile(r"^jerga-remind-(\d+)\.(?:timer|service)$")
_PROX = re.compile(r"^(\w{3} \d{4}-\d{2}-\d{2} \d{2}:\d{2})")


class _CtlError(Exception):
    """systemctl no está o no responde."""


def parse_when(texto: str, now: datetime | None = None) -> tuple[str, str]:
    """«20m»/«1 h»/«90 segundos» → («--on-active=1200», «en 20 minutos»); «18:00» ya pasado hoy → mañana."""
    texto = texto.strip().lower()
    if m := _REL.match(texto):
        n = int(m.group(1))
        sufijo = m.group(2)
        factor, palabra = (1, "segundo") if sufijo.startswith("s") else \
                          (60, "minuto") if sufijo.startswith("m") else (3600, "hora")
        return f"--on-active={n * factor}", f"en {n} {palabra}{'' if n == 1 else 's'}"
    if m := _HHMM.match(texto):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            raise ValueError(texto)
        base = now or datetime.now()
        objetivo = base.replace(hour=h, minute=mi, second=0, microsecond=0)
        if objetivo <= base:  # acaba de pasar (o es justo ahora): mañana
            objetivo += timedelta(days=1)
        cuando = "hoy" if objetivo.date() == base.date() else "mañana"
        return f"--on-calendar={objetivo:%Y-%m-%d %H:%M:%S}", f"{cuando} a las {objetivo:%H:%M}"
    raise ValueError(texto)


def fired_cmd(texto: str) -> list[str]:
    """Comando que dispara el timer: notify-send + jerga say, con las comillas del texto escapadas para sh."""
    seguro = texto.replace("'", "'\\''")
    return ["sh", "-c", f"notify-send -t 60000 Recordatorio '{seguro}'; jerga say 'Recordatorio: {seguro}'"]


def _systemctl(args: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                              timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _json_tabla(texto: str) -> list:
    """Parsea la salida JSON de systemctl (tolera la leyenda «N timers listed.» que va detrás)."""
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        i, j = texto.find("["), texto.rfind("]")
        return json.loads(texto[i:j + 1]) if 0 <= i < j else []


def _unidades() -> list[dict]:
    """Unidades jerga-remind-* cargadas (timers y servicios) con su description."""
    res = _systemctl(["list-units", "jerga-remind-*", "--all", "--output=json"])
    if res is None or res.returncode != 0:
        raise _CtlError
    return [e for e in _json_tabla(res.stdout) if isinstance(e, dict)]


def next_unit() -> str:
    """Nombre libre para el siguiente timer: máximo de las unidades existentes (timer o servicio) + 1."""
    numeros = []
    for e in _unidades():
        if m := _NUMERO.match(e.get("unit", "")):
            numeros.append(int(m.group(1)))
    return f"jerga-remind-{max(numeros, default=0) + 1}"


def _timers() -> list[dict]:
    """Timers jerga-remind-* vivos, con unit y next (cuándo disparan)."""
    res = _systemctl(["list-timers", "jerga-remind-*", "--all", "--output=json"])
    if res is None or res.returncode != 0:
        raise _CtlError
    return [e for e in _json_tabla(res.stdout) if isinstance(e, dict)]


def _descriptions() -> dict[int, str]:
    """nº → texto del recordatorio (recuperado de la Description de la unidad); sin systemctl, vacío."""
    try:
        out = {}
        for e in _unidades():
            if m := _NUMERO.match(e.get("unit", "")):
                desc = e.get("description", "")
                out[int(m.group(1))] = desc[len(_PREFIJO):] if desc.startswith(_PREFIJO) else desc
        return out
    except _CtlError:
        return {}


def _fmt_cuando(proximo: str) -> str:
    """«Mon 2026-11-09 18:00:00 CET» → «Mon 2026-11-09 18:00» (más legible por voz)."""
    m = _PROX.match(proximo.strip())
    return m.group(1) if m else proximo.strip()


def _segundos(cuando_arg: str, now: datetime) -> float:
    """Segundos hasta que dispara un --on-active/--on-calendar (para el aviso de «>1 h vista»)."""
    valor = cuando_arg.split("=", 1)[1]
    if cuando_arg.startswith("--on-active="):
        return float(valor)
    return (datetime.strptime(valor, "%Y-%m-%d %H:%M:%S") - now).total_seconds()


def _listar() -> int:
    if shutil.which("systemctl") is None:
        print("no puedo: systemctl no está en PATH")
        return EXIT_ERROR
    try:
        timers = _timers()
    except _CtlError:
        print("no puedo leer los recordatorios: systemctl no responde")
        return EXIT_ERROR
    descs = _descriptions()
    filas = []
    for e in timers:
        if m := _NUMERO.match(e.get("unit", "")):
            n = int(m.group(1))
            filas.append((n, _fmt_cuando(e.get("next", "")), descs.get(n, "?")))
    if not filas:
        print("sin recordatorios")
        return EXIT_OK
    for n, cuando, texto in sorted(filas):
        print(f"{n}) {cuando} — {texto}")
    return EXIT_OK


def _cancelar(args: list[str]) -> int:
    if len(args) != 1 or not args[0].isdigit():
        print(_USO, file=sys.stderr)
        return EXIT_ERROR
    n = int(args[0])
    if shutil.which("systemctl") is None:
        print("no puedo: systemctl no está en PATH")
        return EXIT_ERROR
    try:
        timers = _timers()
    except _CtlError:
        print("no puedo leer los recordatorios: systemctl no responde")
        return EXIT_ERROR
    if not any(e.get("unit") == f"jerga-remind-{n}.timer" for e in timers):
        print(f"no hay recordatorio número {n}")
        return EXIT_ERROR
    res = _systemctl(["stop", f"jerga-remind-{n}.timer", f"jerga-remind-{n}.service"])
    if res is None or res.returncode != 0:
        print(f"no pude cancelar el recordatorio {n}")
        return EXIT_ERROR
    texto = _descriptions().get(n)
    print(f"cancelado: {texto}" if texto else f"cancelado el recordatorio {n}")
    return EXIT_OK


def _crear(texto: str, cuando: str) -> int:
    if shutil.which("systemd-run") is None:
        print("no puedo: systemd-run no está en PATH")
        return EXIT_ERROR
    if shutil.which("systemctl") is None:
        print("no puedo: systemctl no está en PATH")
        return EXIT_ERROR
    ahora = datetime.now()
    try:
        cuando_arg, humano = parse_when(cuando, ahora)
        unit = next_unit()
    except ValueError:
        print(f"no entiendo «{cuando}»: {_USO}", file=sys.stderr)
        return EXIT_ERROR
    except _CtlError:
        print("no puedo: systemctl no responde")
        return EXIT_ERROR
    cmd = ["systemd-run", "--user", cuando_arg, f"--unit={unit}",
           f"--description={_PREFIJO}{texto}", *fired_cmd(texto)]
    try:  # lista de args, nunca shell=True: el sh -c va como argumento de systemd-run
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        print("no pude crear el recordatorio: systemd-run no responde")
        return EXIT_ERROR
    if res.returncode != 0:
        print(f"no pude crear el recordatorio: {(res.stderr.strip() or 'systemd-run falló')[:120]}")
        return EXIT_ERROR
    n = unit.rsplit("-", 1)[1]
    print(f"recordatorio {n}: {texto} — {humano}")
    if _segundos(cuando_arg, ahora) > 3600:  # unidades transitorias: no sobreviven a un apagón
        print("ojo: si apagas el equipo, se pierde")
    if not is_running():  # el timer dispara igual, pero sin servicio no hay voz
        print("Trinity no sonará: jerga está parado")
    return EXIT_OK


def main(argv: list[str]) -> int:
    if sys.platform == "win32":
        print("Todavía no sé poner recordatorios en Windows.")
        return EXIT_ERROR
    if argv[:1] == ["--list"]:
        return _listar()
    if argv[:1] == ["--cancel"]:
        return _cancelar(argv[1:])
    if len(argv) >= 3 and argv[1].lower() == "en":
        return _crear(argv[0], " ".join(argv[2:]))
    print(_USO, file=sys.stderr)
    return EXIT_ERROR
