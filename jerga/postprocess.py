"""Correcciones: reemplazos deterministas + (opcional) LLM local."""
from __future__ import annotations

import re

from .config import log


class PostProcessor:
    def __init__(self, replacements: dict, llm: dict, vocabulary: list[str]):
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
        return self.apply_llm(self.apply_rules(text))
