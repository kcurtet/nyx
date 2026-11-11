# Plan de implementación: vim y programar por voz (spec 007)

> Ejecutar con la skill `executing-plans`, tarea a tarea. Pasos con checkbox `- [ ]`.

**Objetivo:** «modo vim borrar línea» pulsa `Esc d d` en nvim (foco); «modo programar …» pega una línea de código con símbolos, comillas explícitas y números.

**Arquitectura:** `commands.py` gana dos prefijos (vim → `Result.keys` con tokens físicos validados léxicamente y resueltos por `vim_layout`; programar → `_join_code` hermana de `_join_path` con espaciado en los valores y retorno temprano). `output.py` gana `Output.press(seq)` (itera `combo()` por token; no-op+log sin capa de teclas). `app.py` ejecuta `res.keys` ANTES de `discard`. Vocabulario y docs en config/README.

**Stack:** Python 3.10+, pytest + monkeypatch, ruff. Sin dependencias nuevas.

**Spec:** `docs/specs/007-vim-y-programar/spec.md`

## Restricciones globales

- Solo `nyx/commands.py`, `nyx/app.py`, `nyx/output.py`, `nyx/config.py`, `config.example.toml`, `README.md` y tests.
- `uv run pytest -q tests` verde (Linux+Windows) y `uvx ruff check .` limpio.
- Tests de teclas SIEMPRE con fakes (nunca evdev/uinput real en CI).
- Orden de prefijos: interrogante/envía/… → código → ruta → vim → programar.
- Un token de la gramática = una llamada a `combo()` (pulsación atómica mod+cuerpo).

## Foco de revisión

1. Rama muerta en app: `res.keys` después de `discard` nunca se ejecuta (hallazgo nº5 del check). Test: T3 (orden de chequeos — el diff debe mostrar el branch antes).
2. Tokens no inyectables (`/` `:` `%` `!` como texto): solo existen `slash`/`colon` lógicos resueltos por layout; letras/dígitos/shift+5/shift+1 universales (hallazgo nº3). Tests: T1.
3. Sufijo `quote_words` («entre comillas» al FINAL de la frase) se pela ANTES del prefijo programar y lo desactiva: mismo precedente que «ruta» — documentado, NO arreglar. Test: T4 (caso documentado).
4. «programar» debe quedar exento de `_inline`/`_lowercase_prev` (hallazgo nº10): retorno temprano. Test: T4.
5. Grammar léxica en parse (commands.py no ve la capa de teclas): mod ∈ {ctrl,shift,alt,super}, cuerpo = 1 alfanumérico o nombre conocido. Test: T1 (A7).

---

### Tarea 1: prefijo vim — Result.keys, gramática, layout (commands.py + config.py)

**Ficheros:**
- Modificar: `nyx/commands.py` (Result, parse), `nyx/config.py` (DEFAULTS)
- Test: `tests/test_postprocess.py` (ahí viven los de prefijos) o `tests/test_commands_vim.py` nuevo si conviene — criterio del builder siguiendo el estilo.

**Interfaces:**
- Produce: `Result.keys: list[str] | None = None`.
- Produce en DEFAULTS `[commands]`: `vim_words: ["vim", "modo vim"]` · `vim_map: dict[str, str]` (~20 mapeos de la spec D-A3, valores con tokens: `d d`, `ctrl+r`, `slash`, `colon w enter`, `shift+a`…) · `vim_layout: "us"`.
- Produce en commands.py: `_VIM_LAYOUTS = {"slash": {"us": "slash", "es": "shift+7"}, "colon": {"us": "shift+semicolon", "es": "shift+dot"}}`; validador léxico `_vim_tokens(seq: str, layout: str) -> list[str] | None` (None = token ilegal); bloque en `parse()` tras `path_words`: prefijo matchea + cuerpo entero (fold, `_PUNCT` limpio) EN el mapa (merge usuario+default) → `Result(text="", discard=True, keys=tokens)`.

- [ ] **Paso 1: tests que fallan** (A1–A7 a nivel parse):

```python
def test_vim_borrar_linea():            # A1: keys=["esc","d","d"], discard, text=""
def test_vim_guardar_por_layout():      # A2: us → ["esc","shift+semicolon","w","enter"]; es → ["esc","shift+dot","w","enter"]
def test_vim_buscar():                  # A3: slash resuelto
def test_vim_fuera_de_mapa_o_solo():    # A4: «vim salta»/«vim» → texto tal cual, keys None
def test_vim_mapa_usuario_gana():       # A5: override "insertar al final" → "esc shift+s" válido
def test_vim_token_ilegal():            # A7: "esc volar" → mapeo ignorado, texto tal cual, log
def test_vim_dos_palabras_prefijo():    # «modo vim …» y «vim …» ambos
```

- [ ] **Paso 2:** `uv run pytest tests/ -k vim -v` → FAIL (sin Result.keys / sin bloque).
- [ ] **Paso 3: implementar.** La frase del mapa se compara plegada y limpia; el cuerpo con palabras extra («vim borrar línea ya») NO matchea (mapa exacto, como toda frase-orden).
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(commands): prefijo vim por voz — Result.keys, gramática léxica y vim_layout`

### Tarea 2: `Output.press` (output.py)

**Ficheros:**
- Modificar: `nyx/output.py` (clase Output)
- Test: `tests/test_output_press.py` (nuevo) o donde convenga.

**Interfaces:**
- Produce: `Output.press(seq: list[str]) -> None` — si `self.keys is None`: log + return. Si no: por cada token `self.keys.combo(token)` con `time.sleep(0.01)` entre tokens (misma cadencia que `combo`). Log de la secuencia.
- Consume: `combo()` de la capa activa (uinput/pynput; ydotool/wtype/xdotool no cubren el set — la validación léxica de T1 filtra, y si `combo` lanza igualmente, capturar por token, log y continuar).

- [ ] **Paso 1: tests que fallan** (fake keys con registro de combos):

```python
def test_press_ejecuta_tokens_en_orden():   # ["esc","d","d"] → combo llamado 3× con esos tokens
def test_press_sin_capa_de_teclas():        # keys=None → no-op, sin excepción, log
def test_press_token_que_falla_sigue():     # combo lanza en un token → log + siguientes se ejecutan
```

- [ ] **Paso 2:** FAIL esperado (sin `press`).
- [ ] **Paso 3: implementar.**
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(output): Output.press ejecuta secuencias de teclas token a token`

### Tarea 3: wiring en app.py

**Ficheros:**
- Modificar: `nyx/app.py` (`_process`, tras la rama `res.action`, ANTES de `res.discard`)
- Test: cubierto por T1+T2 (parse produce keys; press las ejecuta) + verificación manual; el branch es mínimo.

**Interfaces:**
- Consume: `Result.keys` (T1), `Output.press` (T2).
- Produce: rama `if res.keys: out.press(res.keys); ui.call(ui.done, f"⌨ {' '.join(res.keys)}"); state/return igual que discard` — ANTES de comprobar `res.discard`. (Texto de UI a criterio del builder.)

- [ ] **Paso 1:** editar `_process` con la rama en el orden correcto (diff mínimamente verificable: la rama keys queda por encima de la de discard).
- [ ] **Paso 2:** suite + ruff (nada rota).
- [ ] **Paso 3:** commit `feat(app): las órdenes vim pulsan teclas vía Output.press`

### Tarea 4: prefijo programar — `_join_code` (commands.py)

**Ficheros:**
- Modificar: `nyx/commands.py`, `nyx/config.py` (`code_line_words` en DEFAULTS)
- Test: junto a los de T1.

**Interfaces:**
- Produce: `code_line_words: ["programar", "modo programar"]` en DEFAULTS; `_CODE_SYMBOLS: dict[str, str]` (multi-palabra incluida como clave: `"es igual a": " = "`, `"punto y coma": ";"`, `"entre comillas": '"'`, `"cierra comillas": '"'`, `"dos puntos": ":"`, números `"cero"…"mil"…` → dígitos); `_join_code(body: str) -> str` (ventana 3→2→1 plegada conservando original, valores con espaciado propio, join final un espacio, limpiar espacios junto a pegados); bloque en `parse()` tras vim → **retorno temprano del resultado** (exento de `_lowercase_prev`/`_inline`).

- [ ] **Paso 1: tests que fallan** (B1–B7):

```python
def test_programar_linea_completa():        # B1: const a = "hello world";
def test_programar_con_numeros():           # B2: si x > 3 devuelve verdadero
def test_programar_comilla_abierta():       # B3: const a = "hola;
def test_programar_fold():                  # B4: PROGRAMAR Guión Bajo x → _x
def test_prioridad_codigo_y_ruta():         # B5
def test_programar_sin_cuerpo():            # B6
def test_programar_dos_puntos_gana_a_dos(): # B7: «dos puntos» → :
def test_programar_exento_de_inline():      # «programar x punto y aparte y» no mete salto raro
```

- [ ] **Paso 2:** FAIL esperado.
- [ ] **Paso 3: implementar** (ventana multi-palabra: igual enfoque que `_join_path`, que ya hace pares).
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(commands): prefijo programar — código de una línea con símbolos, comillas y números`

### Tarea 5: vocabulario, docs y verificación final

**Ficheros:**
- Modificar: `nyx/config.py` (vocabulary), `config.example.toml`, `README.md`

- [ ] **Paso 1:** añadir al `vocabulary` default las palabras nuevas (frases vim, símbolos, números); `config.example.toml`: sección `[commands]` con `vim_words`, `vim_map` de ejemplo (uno redefinido), `vim_layout`, `code_line_words`; README: filas de uso + nota «vim va a la ventana con foco» + nota de `vim_layout` (síntoma del layout mal puesto) + recordatorio de que `vocabulary` del usuario reemplaza el default.
- [ ] **Paso 2:** `uv run pytest -q tests && uvx ruff check .`
- [ ] **Paso 3:** commit `docs(config,readme): vim y programar — vocabulario y documentación`

## Verificación final (manual, PENDIENTE para el humano — NO ejecutar)

Con el servicio actualizado y nvim con foco: «modo vim borrar línea» borra; «modo vim guardar» guarda; en cualquier editor, «modo programar const a es igual a entre comillas hello world cierra comillas punto y coma» pega `const a = "hello world";`. Probar `vim_layout` con el teclado ES si toca.

## Notas para el implementador

- NO redesignes `Output`/`combo`: `press` es un bucle fino encima.
- Los valores del mapa llevan el espaciado (« = » con espacios, «;» sin): no añadas lógica de espaciado aparte.
- Conflictos con el plan → ruling al ledger (`docs/specs/007-vim-y-programar/progress.md`); la spec manda.
- Sufijo «entre comillas» al final de frase (quote_words existente) desactiva programar: comportamiento heredado de «ruta», documentado, no arreglar.
