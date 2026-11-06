# 004 — «ruta»: dictar paths pronunciando los símbolos

## Contexto

Decir una ruta al dictar no funciona: Whisper escribe lenguaje natural («tilde barra dev» aparece como frase con espacios y a veces traducido). Ya existe el patrón de comando-prefijo «código …» (`code_words`) que envuelve en backticks; falta el equivalente para paths, que necesita traducir símbolos hablados y pegar sin espacios.

Decisión del humano: construirlo (sesión 2026-11-06, propuesta aceptada).

## Objetivo

«ruta tilde barra dev barra vigia barra docs barra apuntes punto md» pega `~/dev/vigia/docs/apuntes.md`.

## Objetivos

1. Comando prefijo configurable `[commands] path_words = ["ruta"]`, hermano de `code_words`, evaluado tras él.
2. Mapa de símbolos hablados (matching plegado como todo el sistema): tilde→~, barra→/, contrabarra y barra invertida→\, punto→., guion→-, guion bajo y bajo→_, dos puntos→:, espacio→un espacio real, arroba→@.
3. El resto de palabras se copian tal cual y se unen SIN espacios (los nombres con espacios usan la palabra «espacio»).
4. Las palabras del mapa entran en el vocabulario por defecto de `[stt]` para que Whisper las espere.

## No-objetivos

- Deletrear letra a letra.
- Rutas con mayúsculas mixtas raras: se escribe lo que Whisper oiga (vocabulary y corrections ya existen para eso).
- Chaining con sufijos (interrogante/envía NO se aplican dentro de ruta en v1: si aparecen, se quedan como palabras).

## Decisiones de implementación

**D1** — En `commands.py`: tras el bloque de `code_words`, mismo patrón de regex para `path_words`; si matchea y queda cuerpo, tokenizar por espacios el cuerpo plegado (conservando el texto original para las palabras), mapear símbolos, unir todo sin espacios y sustituir «espacio» por un espacio. Si solo se dijo la palabra, comportamiento estándar: se escribe tal cual.
**D2** — El resultado es texto plano pegado (sin backticks; para código ya está «código»).
**D3** — `config.py` DEFAULTS: añade a `vocabulary` las palabras nuevas; `config.example.toml` documenta el comando con ejemplo.
**D4** — README: fila en la tabla de uso.

## Restricciones

- Suite verde (Linux+Windows) y ruff; sin dependencias nuevas; solo `commands.py`, `config.py`, `config.example.toml`, `README.md` y tests.

## Criterios de aceptación (Given/When/Then)

- **A1** G: «ruta tilde barra dev barra música» T: `~/dev/música`.
- **A2** G: «ruta docs barra specs punto md» T: `docs/specs.md`.
- **A3** G: «ruta mi espacio proyecto» T: `mi proyecto` (espacio real solo por la palabra).
- **A4** G: «ruta doble punto barra barra docs» T: `../docs` (palabras no-símbolo se copian: «doble punto» NO se mapea a ..; solo mapea el mapa exacto — «doble punto» son dos palabras y van tal cual). Nota: esto es aceptable en v1; documentado.
- **A5** G: «RUTA Guión Bajo barra X» (mayúsculas/tilde) T: mapea igual (_fold).
- **A6** G: solo «ruta» T: se escribe «ruta» tal cual.
- **A7** G: «código git status» sigue intacto; «ruta …» no interfiere.

## Casos límite

- Carpeta que se llame igual que un símbolo («carpeta punto»): la palabra se mapea (ambigüedad asumida en v1, documentada).
- «ruta» dentro de una frase normal SIN ser prefijo inicial: no hace nada (es comando de prefijo).
- Combinación con prefijo «código» («código ruta …»): gana código; va con backticks.

## Qué queda a criterio del builder

- Helpers internos y forma del mapa (dict módulo-nivel).
- Mensajes/test naming, siguiendo el estilo de test existente.

## Preguntas abiertas

- ¿Mapear «doble punto»→.. y «punto punto»→..? Fácil de añadir luego si molesta en el uso real.
