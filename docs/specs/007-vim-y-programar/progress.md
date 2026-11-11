# Ledger — plan: docs/specs/007-vim-y-programar/plan.md

Baseline: 217 passed, ruff limpio (rama hd/impl-007 desde main).

Task 1: complete (commit c1963cb, tests: `uv run pytest tests/test_commands_vim.py -q` → 13 fail → 14 passed; suite completa 231 passed + ruff limpio).

Task 2: complete (commit 40bcff7, tests: `uv run pytest tests/test_output_press.py -q` → 6 fail → 6 passed; suite completa 237 passed + ruff limpio). Ruling: spec D6 manda no-op si la capa no es uinput/pynput, pero el plan solo comprobaba `keys is None` — se implementa AMBAS: marca de clase `PRESS_CAPABLE` en UInputKeys/PynputKeys (chequeo previo con log claro) + try por token del plan — coste: atributo de clase nuevo en output.py y los fakes de test lo declaran (un test con un fake sin la marca sería no-op: documentado en el propio test partial).

Task 3: complete (commit eaaf358, tests: `uv run pytest -q tests` → 238 passed + ruff limpio; test de orden `test_app_comprueba_keys_antes_de_discard` → fail antes del edit, pass después). Nota: primer intento colocó la rama DESPUÉS de discard (el test de orden lo habría cazado); corregido antes de commit.

Task 4: complete (commit b39b331, tests: `uv run pytest tests/test_commands_vim.py -q` → 9 fail → 27 passed; suite completa 251 passed + ruff limpio). Rulings: (1) las claves de _CODE_SYMBOLS se PLEGAN al construir el dict — el lookup es plegado y «más»/«dieciséis» con tilde no casaban (bug cazado por el test rojo) — coste: dict-comprehension wrapper, cero cambio de comportamiento. (2) Valores como tuplas (pegado, espacio_antes, espacio_después) en vez de strings con espaciado literal — la comilla '"' abre (espacio antes, pega a la derecha) y cierra (pega a la izquierda, espacio después) con espaciado DIRECCIONAL distinto para el mismo carácter, no expresable como string plano — coste: el mapa interno no son strings puros (es estructura privada del builder, permitido); el espaciado de la spec queda codificado 1:1 en las tuplas. Números espaciados como palabras (pegan junto a guion bajo: «x_2», y no rompen «espera 20 segundos»).
