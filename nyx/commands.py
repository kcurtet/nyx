"""Comandos de voz: palabras que no se escriben, sino que hacen algo.

Al final de la frase (se pueden encadenar: "…interrogante envía"):
  interrogante        → ¿…?
  exclamación         → ¡…!
  entre comillas      → "…"
  KX minúsculas       → minusculiza la palabra anterior (inline)
  envía               → pega y pulsa Enter
  borra eso           → no pega nada
Al principio:
  código …            → `…`
  ruta …              → path con símbolos hablados, pegado sin espacios
                        ("ruta tilde barra dev barra docs punto md" → ~/dev/docs.md)
En cualquier sitio:
  nueva línea         → salto de línea
  punto y aparte      → punto + salto de línea

Se comparan sin tildes ni mayúsculas. Todas las palabras se configuran en [commands].
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .config import log

_PUNCT = " \t.,;:!¡?¿…"
_SOFT = " \t,;:"  # lo que se limpia sin perder el punto final de la frase


@dataclass
class Result:
    text: str
    send: bool = False  # pulsar Enter después de pegar
    discard: bool = False  # no pegar nada
    action: str | None = None  # frase-orden completa: "read" (leer selección) · "hush" (callar)
    keys: list[str] | None = None  # «vim»: secuencia de teclas a pulsar (tokens físicos)


def _fold(s: str) -> str:
    """Minúsculas y sin tildes, carácter a carácter (conserva las posiciones)."""
    out = []
    for c in s:
        d = unicodedata.normalize("NFD", c)
        out.append((d[0] if d else c).lower())
    return "".join(out)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


# Símbolos hablados del comando «ruta» (matching plegado, como todo el sistema).
# Frases de dos palabras antes que sus partes: "barra invertida" gana a "barra".
_PATH_SYMBOLS = {
    "tilde": "~",
    "barra": "/",
    "contrabarra": "\\",
    "barra invertida": "\\",
    "punto": ".",
    "guion": "-",
    "guion bajo": "_",
    "bajo": "_",
    "dos puntos": ":",
    "espacio": " ",
    "arroba": "@",
}


def _join_path(body: str) -> str:
    """Cuerpo de «ruta …»: mapea símbolos hablados y une todo SIN espacios."""
    words = [w.strip(".,;:!¡¿…\"'«»()") for w in body.split()]
    out = []
    i = 0
    while i < len(words):
        pair = " ".join(_fold(w) for w in words[i:i + 2])
        if pair in _PATH_SYMBOLS:  # primero la frase larga ("guion bajo", "dos puntos"…)
            out.append(_PATH_SYMBOLS[pair])
            i += 2
        else:
            out.append(_PATH_SYMBOLS.get(_fold(words[i]), words[i]))
            i += 1
    return "".join(out)


# ------------------------------------------------------------- vim por voz
# Gramática LÉXICA de los tokens de vim_map (commands.py no ve la capa de teclas):
# token = cuerpo o mod+cuerpo (mod repetible); cuerpo = 1 alfanumérico ASCII o nombre conocido.
# / y : NO son inyectables igual en US y ES: solo existen los tokens lógicos slash/colon,
# que vim_layout resuelve a teclas físicas. Letras y shift+5/shift+1 son universales.
_VIM_MODS = {"ctrl", "shift", "alt", "super"}
_VIM_BODIES = {
    "enter", "esc", "semicolon", "dot", "slash", "colon", "backspace", "tab", "space",
    "left", "right", "up", "down", "home", "end", "delete", "insert", "pageup", "pagedown",
}
_VIM_LAYOUTS = {
    "slash": {"us": "slash", "es": "shift+7"},
    "colon": {"us": "shift+semicolon", "es": "shift+dot"},
}


def _vim_tokens(seq: str, layout: str) -> list[str] | None:
    """Secuencia de vim_map → tokens físicos; None si algún token no casa la gramática
    (el mapeo entero se ignora y la frase se escribe tal cual)."""
    out = []
    for token in seq.split():
        parts = token.split("+")
        body, mods = parts[-1], parts[:-1]
        if any(m not in _VIM_MODS for m in mods) or not (
            (len(body) == 1 and body.isascii() and body.isalnum()) or body in _VIM_BODIES
        ):
            log("[vim] token ilegal, mapeo ignorado:", token)
            return None
        # tokens lógicos: el layout decide la tecla física (y sus modificadores)
        out.append(_VIM_LAYOUTS.get(body, {}).get(layout, token))
    return out


# ------------------------------------------------------------- en medio
def _inline(text: str, words: list[str], insert: str, capitalize_next: bool) -> str:
    for w in sorted(words, key=len, reverse=True):
        rx = re.compile(r"[\s,;:.]*(?<!\w)" + re.escape(_fold(w)) + r"(?!\w)[\s,;:.]*")
        while True:
            m = rx.search(_fold(text))
            if not m:
                break
            before, after = text[: m.start()], text[m.end():]
            if capitalize_next:
                after = _cap(after)
            text = before + insert + after
    return text


def _lowercase_prev(text: str, words: list[str]) -> str:
    """"KX minúsculas" → minusculiza la palabra ANTERIOR al comando y lo quita."""
    cambio = False
    completos = {_fold(w) for w in words}
    for w in sorted(words, key=len, reverse=True):
        rx = re.compile(r"(\w+)[\s,;:.¿¡]*" + re.escape(_fold(w)) + r"(?!\w)")
        while True:
            m = rx.search(_fold(text))
            if not m:
                break
            # "en minúsculas" a secas: la palabra previa es el conector del comando, no un objetivo
            if m.start() == 0 and any(c.startswith(_fold(m.group(1)) + " ") for c in completos):
                break
            cambio = True
            text = text[: m.start()] + m.group(1).lower() + text[m.end():]
    return text.rstrip(_PUNCT) if cambio else text


# ------------------------------------------------------------- al final
_SUFFIX_KINDS = (
    "question_words", "exclamation_words", "quote_words",
    "send_words", "discard_words",
)
_MARKS = {"question_words": ("¿", "?"), "exclamation_words": ("¡", "!")}


def parse(text: str, commands: dict) -> Result:
    res = Result(text)
    if not text or not commands:
        return res
    # Frases-orden: SOLO si es todo lo que has dicho ("léeme esto", "calla").
    whole = _fold(text).strip(_PUNCT + "\"'«»")
    for kind, action in (("read_words", "read"), ("hush_words", "hush")):
        if whole in {_fold(w) for w in commands.get(kind) or []}:
            return Result("", action=action)
    open_marks = commands.get("spanish_open_marks", commands.get("spanish_open_question", True))

    triggers = sorted(
        ((_fold(w), kind) for kind in _SUFFIX_KINDS for w in (commands.get(kind) or [])),
        key=lambda t: -len(t[0]),
    )
    # Pelamos comandos del final uno a uno ("…interrogante envía" → envía, luego interrogante).
    progress = True
    while progress:
        progress = False
        stripped = res.text.rstrip(_PUNCT)
        folded = _fold(stripped)
        for w, kind in triggers:
            m = re.search(r"(?:^|[\s,;:.¿¡])" + re.escape(w) + r"$", folded)
            if not m:
                continue
            body = stripped[: m.start()]
            if not body.strip(_PUNCT):
                return res  # solo dijo la palabra: se escribe tal cual
            if kind == "discard_words":
                return Result("", discard=True)
            if kind in _MARKS:
                opening, closing = _MARKS[kind]
                body = body.rstrip(_PUNCT).lstrip("¿¡ ")
                res.text = (opening + _cap(body) if open_marks else body) + closing
            elif kind == "quote_words":
                res.text = '"' + body.rstrip(_PUNCT).lstrip("¿¡ ") + '"'
            elif kind == "send_words":
                res.send = True
                res.text = body.rstrip(_SOFT)
            progress = True
            break

    # ---- al principio: "código git status" → `git status`
    for w in sorted(commands.get("code_words") or [], key=len, reverse=True):
        m = re.match(r"[\s¿¡]*" + re.escape(_fold(w)) + r"[\s,;:.]+", _fold(res.text))
        if m and res.text[m.end():].strip(_PUNCT):
            res.text = "`" + res.text[m.end():].rstrip(_PUNCT) + "`"
            break

    # ---- al principio: "ruta tilde barra dev" → ~/dev (tras «código»: "código ruta …" gana código)
    for w in sorted(commands.get("path_words") or [], key=len, reverse=True):
        m = re.match(r"[\s¿¡]*" + re.escape(_fold(w)) + r"[\s,;:.]+", _fold(res.text))
        if m and res.text[m.end():].strip(_PUNCT):
            res.text = _join_path(res.text[m.end():].rstrip(_PUNCT))
            break

    # ---- al principio: "modo vim borrar línea" → pulsa teclas (tras «ruta"); mapa exacto
    for w in sorted(commands.get("vim_words") or [], key=len, reverse=True):
        m = re.match(r"[\s¿¡]*" + re.escape(_fold(w)) + r"[\s,;:.]+", _fold(res.text))
        if not m:
            continue
        fmap = {_fold(k): v for k, v in (commands.get("vim_map") or {}).items()}
        body = _fold(res.text[m.end():]).strip(_PUNCT + "\"'«»")
        if body in fmap:
            tokens = _vim_tokens(fmap[body], commands.get("vim_layout") or "us")
            if tokens is not None:
                return Result("", discard=True, keys=tokens)
        break  # prefijo reconocido pero frase fuera del mapa: se escribe tal cual

    # ---- en cualquier sitio
    res.text = _lowercase_prev(res.text, commands.get("lowercase_words") or [])
    res.text = _inline(res.text, commands.get("paragraph_words") or [], ".\n", capitalize_next=True)
    res.text = _inline(res.text, commands.get("newline_words") or [], "\n", capitalize_next=False)
    return res


def apply_voice_commands(text: str, commands: dict) -> str:
    return parse(text, commands).text
