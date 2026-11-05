"""Correcciones: reemplazos deterministas + (opcional) LLM local."""
from __future__ import annotations

import re

from .commands import Result, apply_voice_commands, parse  # noqa: F401  (reexportados)
from .config import log


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

    # "package .json" → "package.json" (Whisper separa a veces la extensión)
    _EXT = re.compile(r"(\w) \.(json|jsonc|js|mjs|ts|tsx|jsx|py|md|ya?ml|toml|lock|sh|env|txt|html|css|rs|go|sql)\b")

    def apply_rules(self, text: str) -> str:
        text = self._EXT.sub(r"\1.\2", text)
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

    def process(self, text: str) -> Result:
        # Comandos antes del LLM: así el LLM no puede "corregir" la palabra "interrogante".
        res = parse(self.apply_rules(text), self.commands)
        if not res.discard:
            res.text = self.apply_llm(res.text)
        return res

    def __call__(self, text: str) -> str:
        return self.process(text).text
