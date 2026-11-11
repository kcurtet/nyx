# 007 — vim y programar por voz

## Contexto

El humano dicta en la terminal y edita con nvim; quiere dos cosas relacionadas:

1. **«modo vim borrar línea» → que nyx PULSE teclas** (`Esc` `d` `d`) en nvim, no que pegue texto.
2. **«modo programar const a es igual a entre comillas hello world cierra comillas punto y coma» → que pegue `const a = "hello world";`** — código de una línea dictado en español.

Infraestructura existente: comandos prefijo en `commands.py` («código» envuelve en backticks, «ruta» spec 004 traduce símbolos sin espacios); `Result.action` ejecutado en app.py; inyección real de teclas (`UInputKeys` con `combo`, detrás de `Output`, que app ya posee); `[stt] vocabulary` para que Whisper espere las palabras nuevas.

Decisiones del humano (sesión 2026-11-09): set inicial ampliable de vim (no gramática por deletreo); «programar» de UNA línea en v1 (sin multilínea ni LLM); uso en terminal y nvim; teclado **US o ES según el momento**; comillas con **toggle explícito** («cierra comillas»); **con números** en el mapa por defecto.

Decisiones del orquestador tras el builder-check (hechos verificados en el código): las teclas son CÓDIGO FÍSICO pre-layout — `/` y `:` no son inyectables igual en US y ES (en ES, `KEY_SLASH` produce `-`); `%`→`shift+5` y `!`→`shift+1` coinciden en ambos; las letras son universales. Mayúsculas solo vía `shift+letra`; C2 se testea con fakes sin extraer dispatcher.

## Objetivo

Dictar «modo vim borrar línea» y ver cómo nvim ejecuta `dd`; dictar «modo programar …» y ver código bien escrito en el cursor.

## Objetivos — A: vim por voz

1. Prefijo configurable `[commands] vim_words` (por defecto `["vim", "modo vim"]`), evaluado tras «ruta».
2. Mapa frase→secuencia, por defecto ~20 mapeos, ampliable en config (`[commands] vim_map`): diccionario frase → secuencia de tokens separados por espacios, `+` para combos (`ctrl+r`), tokens lógicos `slash` y `colon` que resuelve el layout.
3. Set inicial: borrar línea (`d d`) · borrar palabra (`d w`) · borrar carácter (`x`) · copiar línea (`y y`) · pegar (`p`) · deshacer (`u`) · rehacer (`ctrl+r`) · insertar (`i`) · insertar al final (`shift+a`) · insertar línea abajo (`o`) · insertar línea arriba (`shift+o`) · siguiente palabra (`w`) · buscar (`slash`) · buscar y reemplazar (`colon % s slash`) · línea de comando (`colon`) · guardar (`colon w enter`) · salir (`colon q enter`) · guardar y salir (`colon w q enter`) · forzar salir (`colon q shift+1 enter`) · principio del fichero (`g g`) · final del fichero (`shift+g`).
4. TODA secuencia empieza con `Esc` (inofensivo en modo normal, salva desde insert/command mode). Los comandos «abiertos» (`slash`, `colon …`) dejan a nvim esperando: así se compone con lo que dictas después.
5. `[commands] vim_layout = "us"` (por defecto; `"es"` disponible): resuelve `slash` → `slash` (tecla directa en US) o `shift+7` (ES); `colon` → `shift+semicolon` (US) o `shift+dot` (ES). Letras y `shift+5`/`shift+1` son universales.

## Objetivos — B: programar una línea

1. Prefijo configurable `[commands] code_line_words` (por defecto `["programar", "modo programar"]`), evaluado tras «vim».
2. Mapa de símbolos hablados (matching plegado, multi-palabra primero — patrón `_join_path` de 004) con espaciado propio en el valor:
   - Comparadores: `es igual a`→` = ` · `no igual a`/`distinto de`→` != ` · `mayor que`→` > ` · `menor que`→` < ` · `mayor o igual`→` >= ` · `menor o igual`→` <= ` · `flecha`→` => `.
   - Comillas TOGGLE EXPLÍCITO: `entre comillas`→`"` (abre) · `cierra comillas`→`"` (cierra) · `entre comillas simples`→`'` · `cierra comillas simples`→`'`. Sin auto-cierre: si no dictas el cierre, queda abierta.
   - Puntuación pegada (sin espacio antes, un espacio después): `punto y coma`→`;` · `dos puntos`→`:` · `coma`→`,` · `punto`→`.`.
   - Aritméticos y otros: `más`→` + ` · `por`→` * ` · `entre`→` / ` · `guion bajo`→`_` · `guion`→`-` · `por ciento`→`%` · `barra vertical`→`|` · `ampersand`→`&`.
   - Números (multi-palabra siempre primero, p.ej. `dos puntos` gana a `dos`): `cero`…`veinte` (0–20), `treinta`…`noventa` (decenas), `cien`, `mil` → dígitos. Compuestos («veintitrés») fuera de v1: config ampliable.
3. El resto de palabras se copia tal cual y se une con UN espacio; el mapa exacto de extras queda a criterio del builder siguiendo este estilo.
4. Resultado pegado como texto normal (mecánica de pegar y sufijos existentes intacta).

## No-objetivos (v1)

- Deletreo por letras y gramática completa de vim (rechazado en conversación).
- Números compuestos («veintitrés», «ciento cincuenta»).
- Multilínea, indentación, auto-pareado de llaves/paréntesis, detección de lenguaje.
- Postproceso LLM de lo dictado.
- Autodetección del layout del teclado (v1: config `vim_layout`).
- Detectar SI el foco es nvim (Wayland no lo permite de forma fiable): las teclas van a la ventana enfocada, siempre.
- Enviar comandos por IPC de nvim (`--server`): keystrokes al foco, más simple y universal.

## Decisiones de implementación

**D1 — Payload de teclas**: `Result` gana `keys: list[str] | None = None` (secuencia de tokens, p. ej. `["esc", "d", "d"]`, `"ctrl+r"` combo, `slash`/`colon` lógicos YA resueltos a tokens físicos en parse según `vim_layout`). `parse()` reconoce prefijo `vim_words` + frase del mapa (fold) → `Result(text="", discard=True, keys=[...])`. app.py `_process`: la rama `res.keys` se comprueba ANTES de `res.discard` y antes de `if not text` (si no, nunca se ejecutaría): ejecuta la secuencia por la capa de teclas de `Output` (nuevo método `Output.press(seq)` que reusa `combo()`; una acción, sin pegar, sin tocar portapapeles) y feedback de UI breve a criterio del builder (p. ej. `⌨ …`). `press()` con capa de teclas ausente (`self.keys is None`, method clipboard) → no-op + log. Frase tras «vim» fuera del mapa → se escribe tal cual.

**D2 — Gramática de tokens y layout**: token = `cuerpo` o `mod+cuerpo` con mod ∈ {ctrl, shift, alt, super} (repetibles). `cuerpo` ∈ letra · dígito · nombre de tecla conocido por la capa (`enter`, `esc`, `semicolon`, `dot`, `7`, `1`, `5`…). La validación es LÉXICA en parse (commands.py no ve la capa de teclas): token que no casa la gramática → todo el mapeo se ignora con log y la frase se escribe tal cual. `vim_map` en DEFAULTS con merge recursivo del config (usuario gana/añade mapeos). `vim_layout` resuelve `slash`/`colon` según D-A5; tokens literales `slash`/`colon` SOLO tras el prefijo vim (el resto de la gramática no los usa).

**D3 — Prefijo programar**: en `commands.py`, tras el bloque de `path_words`: regex prefijo → cuerpo → `_join_code(body)` hermana de `_join_path`: tokeniza plegado conservando original, mapea multi-palabra primero (ventana 3→2→1), símbolos con su espaciado propio, join final con un espacio y limpieza de espacios alrededor de pegados. El resultado de `programar` QUEDA EXENTO de los pases posteriores `_lowercase_prev`/`_inline` («punto y coma» ya se consumió; «punto y aparte» dentro de programar no debe romper la línea): retorno temprano, como corresponde a un modo propio.

**D4 — Vocabulario**: las palabras nuevas (frases vim, símbolos y números de programar) entran al `vocabulary` default de `[stt]`. Nota documentada: `vocabulary` del usuario REEMPLAZA la lista default (comportamiento existente de `_merge`; precedente 004) — README lo recuerda.

**D5 — Documentación**: README (tabla de uso + nota de `vim_layout` y de que «vim» va al foco) y `config.example.toml` con ejemplos de ambos prefijos y cómo ampliar `vim_map`.

**D6 — Capas de respaldo Linux**: `press` documentado como función completa con uinput (y Pynput en Windows). YdotoolKeys/WtypeKeys/XdotoolKeys no cubren el set (tablas parciales/keysyms): si la capa activa no es uinput/pynput, `press` hace no-op + log claro, no crash.

## Restricciones

- Solo `nyx/commands.py`, `nyx/app.py`, `nyx/output.py` (método `press`), `nyx/config.py`, `config.example.toml`, `README.md` y tests.
- Suite verde (Linux + Windows) y ruff; sin dependencias nuevas.
- Orden de prefijos documentado y testeado: interrogante/envía → código → ruta → vim → programar (gana el primero que matchee).

## Criterios de aceptación (Given/When/Then)

**Vim:**
- **A1** G: «modo vim borrar línea» T: nyx pulsa `Esc d d` (secuencia capturada por fake en test; en manual, nvim borra la línea) y NO pega texto.
- **A2** G: «modo vim guardar» con `vim_layout="us"` T: `Esc shift+semicolon w Enter`. Con `"es"` T: `Esc shift+dot w Enter`.
- **A3** G: «modo vim buscar» T: `Esc` + token resuelto de `slash` según layout; nvim queda esperando patrón.
- **A4** G: «vim» solo, o frase fuera del mapa («vim salta») T: se escribe tal cual, cero teclas.
- **A5** G: config redefine `"insertar al final": "esc shift+s"` T: gana el usuario y `shift+s` valida en la gramática (letras sueltas = minúsculas; mayúscula solo con `shift+`).
- **A6** G: «modo vim rehacer» T: `Esc ctrl+r`.
- **A7** G: secuencia de config con token ilegal («esc volar») T: mapeo ignorado con log, frase escrita tal cual.

**Programar:**
- **B1** G: «modo programar const a es igual a entre comillas hello world cierra comillas punto y coma» T: pega `const a = "hello world";`
- **B2** G: «programar si x mayor que tres devuelve verdadero» T: `si x > 3 devuelve verdadero` (números del mapa; palabras tal cual).
- **B3** G: «programar const a es igual a entre comillas hola punto y coma» (sin «cierra comillas») T: `const a = "hola;` — queda abierta (toggle explícito, no adivina).
- **B4** G: «PROGRAMAR Guión Bajo x» (mayúsculas/tildes) T: mapea igual por `_fold` → `_x`.
- **B5** G: «código git status» y «ruta …» T: siguen intactos; «código programar x» T: gana «código» (backticks).
- **B6** G: «modo programar» sin cuerpo T: se escribe tal cual.
- **B7** G: «programar dos puntos» T: `:` (multi-palabra gana al número `2`).

**Integración:**
- **C1** G: dictado normal sin prefijos. T: cero cambios de comportamiento.
- **C2** (unit, con fakes) G: `parse` devuelve `keys` válido. T: `Output.press` ejecuta la secuencia vía la capa de teclas fakeada y no toca portapapeles; `res.keys` se comprueba antes que `discard` (la rama muerte está cubierta por test del flujo o por orden de chequeos testeado en el unit de parse+press).

## Casos límite

- «vim» dentro de frase normal sin ser prefijo inicial: nada (es comando prefijo).
- Focus no-nvim al ejecutar «vim …»: las teclas van al foco (documentado; el Esc inicial reduce el daño).
- Layout mal configurado: `slash`/`colon` producen el símbolo del OTRO layout (p. ej. `-` en ES con config US): documentado en README; un cambio de `vim_layout` lo arregla.
- Capa de teclas sin uinput (ydotool/wtype/xdotool activos): `press` no-op con log claro (D6).
- Whisper confunde «vim»/«bim» o «punto y coma»/«punto coma»: vocabulary + reemplazos existentes; añadir corrections obvias es opcional del builder.
- «programar» con palabras que SON símbolos («punto» como palabra de un identificador): ambigüedad asumida en v1 (igual que 004), documentada.

## Qué queda a criterio del builder

- Set exacto de extras del mapa de programar (siguiendo el estilo D3) y sus espaciados.
- Feedback visual exacto del press en la UI.
- Nombres internos (`_join_code`, `press`) y estructura del merge de `vim_map`.
- Tests concretos siguiendo el estilo de test_postprocess.py / test_orders.py (fakes para teclas).

## Preguntas abiertas

- ¿Componer «vim buscar» + patrón dictado en un solo dictado («vim buscar hola» → `/hola`)? Default v1: no — «buscar» deja a nvim esperando y dictas el patrón con un dictado normal. Si molesta, feature futura.
- ¿Auto-detección del layout (consultar xkb/kwin)? Default v1: no, config manual.
