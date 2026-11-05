"""Correcciones: reemplazos deterministas + (opcional) LLM local."""
from __future__ import annotations

import re

from .config import log


_TRAILING_PUNCT = " \t.,;:!¡?¿…"


def apply_voice_commands(text: str, commands: dict) -> str:
    """Comandos dichos al final de la frase.

    "¿has hecho el push pregunta" → "¿Has hecho el push?"
    """
    words = commands.get("question_words") or []
    stripped = text.rstrip(_TRAILING_PUNCT)
    for w in sorted(words, key=len, reverse=True):
        m = re.search(r"(?:^|[\s,;:])" + re.escape(w) + r"$", stripped, re.IGNORECASE)
        if not m:
            continue
        body = stripped[: m.start()].rstrip(_TRAILING_PUNCT)
        if not body:
            return text  # solo dijo "pregunta": lo dejamos tal cual
        body = body.lstrip("¿¡ ")
        if commands.get("spanish_open_question", True):
            body = "¿" + body[:1].upper() + body[1:]
        return body + "?"
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
