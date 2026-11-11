# Ledger — plan: docs/specs/007-vim-y-programar/plan.md

Baseline: 217 passed, ruff limpio (rama hd/impl-007 desde main).

Task 1: complete (commit c1963cb, tests: `uv run pytest tests/test_commands_vim.py -q` → 13 fail → 14 passed; suite completa 231 passed + ruff limpio).

Task 2: complete (commit 40bcff7, tests: `uv run pytest tests/test_output_press.py -q` → 6 fail → 6 passed; suite completa 237 passed + ruff limpio). Ruling: spec D6 manda no-op si la capa no es uinput/pynput, pero el plan solo comprobaba `keys is None` — se implementa AMBAS: marca de clase `PRESS_CAPABLE` en UInputKeys/PynputKeys (chequeo previo con log claro) + try por token del plan — coste: atributo de clase nuevo en output.py y los fakes de test lo declaran (un test con un fake sin la marca sería no-op: documentado en el propio test partial).

Task 3: complete (commit eaaf358, tests: `uv run pytest -q tests` → 238 passed + ruff limpio; test de orden `test_app_comprueba_keys_antes_de_discard` → fail antes del edit, pass después). Nota: primer intento colocó la rama DESPUÉS de discard (el test de orden lo habría cazado); corregido antes de commit.

Task 4: complete (commit b39b331, tests: `uv run pytest tests/test_commands_vim.py -q` → 9 fail → 27 passed; suite completa 251 passed + ruff limpio). Rulings: (1) las claves de _CODE_SYMBOLS se PLEGAN al construir el dict — el lookup es plegado y «más»/«dieciséis» con tilde no casaban (bug cazado por el test rojo) — coste: dict-comprehension wrapper, cero cambio de comportamiento. (2) Valores como tuplas (pegado, espacio_antes, espacio_después) en vez de strings con espaciado literal — la comilla '"' abre (espacio antes, pega a la derecha) y cierra (pega a la izquierda, espacio después) con espaciado DIRECCIONAL distinto para el mismo carácter, no expresable como string plano — coste: el mapa interno no son strings puros (es estructura privada del builder, permitido); el espaciado de la spec queda codificado 1:1 en las tuplas. Números espaciados como palabras (pegan junto a guion bajo: «x_2», y no rompen «espera 20 segundos»).

Task 5: complete (commit b67aa03, tests: `uv run pytest tests/test_commands_vim.py::test_vocabulario_cubre_los_mapas` → fail → pass; suite completa 252 passed + ruff limpio). Ruling: el test de vocabulario compara PLEGADO contra las claves de vim_map y _CODE_SYMBOLS (cubre derivas futuras de ambos mapas) — coste: import privado _CODE_SYMBOLS/_fold en test (patrón ya usado por la suite). Bug de TOML cazado al redactar el ejemplo: `code_line_words` después de la subtabla `[commands.vim_map]` habría caído DENTRO del mapa — verificado parseando el example con tomllib antes de commit.

## Rulings (resumen)

1. **D6 vs plan T2** (capas parciales): spec manda no-op si la capa no es uinput/pynput; plan solo comprobaba `keys is None`. Ambos: marca `PRESS_CAPABLE` en UInputKeys/PynputKeys (no-op + log claro para ydotool/wtype/xdotool) MÁS try-por-token del plan. Coste: atributo de clase nuevo; los fakes de test lo declaran.
2. **Claves plegadas en _CODE_SYMBOLS**: necesario para «más»/«dieciséis» (el test rojo lo pilló). Coste: wrapper de dict, sin cambio observable.
3. **Tuplas con espaciado direccional** en vez de strings con espacios literales: el mismo `"` abre y cierra con espaciado distinto; no expresable como string. El espaciado de la spec (« = », «;» sin espacio antes y uno después) queda codificado 1:1. Coste: los valores del mapa no son strings puros (estructura privada del builder).
4. **Orden de la rama keys en app.py**: tal cual spec D1/trampa 1; además el test `test_app_comprueba_keys_antes_de_discard` clava el orden en el fuente (foco de revisión nº1 del plan). Coste: test frágil a refactors cosméticos del if.

## Minors diferidos

- «mayor o igual QUE» (español natural) deja un «que» suelto: las claves de la spec van sin «que» y la ventana del plan es 3→2→1. Subir a ventana 4 si molesta.
- Trampa heredada de «ruta» (documentada, NO arreglada por mandato): «entre comillas» al FINAL de la frase se pela como sufijo antes del prefijo programar y lo desactiva → `"programar di"` envuelto en comillas. Test: `test_programar_sufijo_entre_comillas_al_final`.
- PostProcessor aplica apply_llm al resultado de programar (discard=False): consistente con «ruta» (comportamiento existente); con LLM activado podría retocar la línea. No tocado (fuera de spec).
- Paréntesis/llaves no están en el mapa (no-objetivo v1): pasan como palabras.

## Verificación final manual — PENDIENTE para el humano (NO ejecutada)

Con el servicio actualizado y nvim con foco: «modo vim borrar línea» borra; «modo vim guardar» guarda; en cualquier editor, «modo programar const a es igual a entre comillas hello world cierra comillas punto y coma» pega `const a = "hello world";`. Probar `vim_layout = "es"` con teclado ES si toca. Evidencia automática: 252 passed (Linux) + ruff limpio; C1 (dictado normal intacto) cubierto por la suite existente.

## Review fixes

- fix(output): alias de símbolos en PynputKeys._k (semicolon/dot/slash como chars; pageup/pagedown → page_up/page_down) — hallazgo único del eje Spec (FIX-FIRST): el enum de pynput no tiene esos nombres y 7 mapeos vim fallaban por token en Windows. Test test_pynput_alias_de_simbolos con fake fiel del enum (visto fallar con AttributeError). Suite 253 passed + ruff limpio.
