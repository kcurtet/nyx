"""Correcciones: reemplazos deterministas + (opcional) LLM local."""
from __future__ import annotations

import re
import unicodedata

from .config import log


_TRAILING_PUNCT = " \t.,;:!¡?¿…"


def _fold(s: str) -> str:
    """Minúsculas y sin tildes, carácter a carácter (conserva las posiciones)."""
    out = []
    for c in s:
        d = unicodedata.normalize("NFD", c)
        out.append((d[0] if d else c).lower())
    return "".join(out)


# comando → (signo de apertura, signo de cierre)
_MARKS = {"question_words": ("¿", "?"), "exclamation_words": ("¡", "!")}


def apply_voice_commands(text: str, commands: dict) -> str:
    """Palabras dichas al final de la frase que la convierten en pregunta o exclamación.

    "has hecho el push interrogante"  → "¿Has hecho el push?"
    "ya funciona el build exclamación" → "¡Ya funciona el build!"
    """
    open_marks = commands.get("spanish_open_marks", commands.get("spanish_open_question", True))
    stripped = text.rstrip(_TRAILING_PUNCT)
    folded = _fold(stripped)
    triggers = [(_fold(w), key) for key in _MARKS for w in (commands.get(key) or [])]
    for w, key in sorted(triggers, key=lambda t: -len(t[0])):
        m = re.search(r"(?:^|[\s,;:])" + re.escape(w) + r"$", folded)
        if not m:
            continue
        body = stripped[: m.start()].rstrip(_TRAILING_PUNCT)
        if not body:
            return text  # solo dijo la palabra: la dejamos tal cual
        opening, closing = _MARKS[key]
        body = body.lstrip("¿¡ ")
        if open_marks:
            body = opening + body[:1].upper() + body[1:]
        return body + closing
    return text


class PostProcessor:
    def __init__(self, replacements: dict, llm: dict, vocabulary: list[str], commands: dict | None = None):
        self.commands = commands or {}
        # Más largos primero para que "docker con pose" gane a "docker".
        self.rules = [
            (re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)", re.IGNORECASE), v)
            for k, v in sorted(replacements.items(), key=lambda kv: -len(kv[0]))
        ]
        self.llm = llm
        self.vocab = vocabulary

    def apply_rules(self, text: str) -> str:
        # varias pasadas: "dóquer con pose" → "Docker con pose" → "docker compose"
        for _ in range(3):
            before = text
            for rx, rep in self.rules:
                text = rx.sub(rep, text)
            if text == before:
                break
        return text

    def apply_llm(self, text: str) -> str:
        if not self.llm.get("enabled") or not text:
            return text
        import httpx

        system = (
            "Corriges transcripciones de voz de un programador que habla español y mezcla "
            "términos técnicos en inglés. Corrige SOLO palabras técnicas mal transcritas "
            "(p. ej. 'guit pus' -> 'git push', 'dóquer' -> 'Docker'). No traduzcas, no reformules, "
            "no añadas ni quites nada más, mantén la puntuación. Responde únicamente con el texto corregido.\n"
            "Glosario: " + ", ".join(self.vocab)
        )
        try:
            r = httpx.post(
                self.llm["url"].rstrip("/") + "/api/chat",
                json={
                    "model": self.llm["model"],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                },
                timeout=self.llm.get("timeout", 4.0),
            )
            r.raise_for_status()
            out = r.json()["message"]["content"].strip().strip('"').strip()
            if not out or len(out) > len(text) * 1.5 + 20:  # el LLM se enrolló
                return text
            return out
        except Exception as e:  # noqa: BLE001
            log(f"[llm] fallo, uso texto sin corregir: {e}")
            return text

    def __call__(self, text: str) -> str:
        # Los comandos van al final: el LLM no debe ver ni tocar la palabra "pregunta".
        return apply_voice_commands(self.apply_llm(self.apply_rules(text)), self.commands)
