# Ledger — plan: docs/specs/007-vim-y-programar/plan.md

Baseline: 217 passed, ruff limpio (rama hd/impl-007 desde main).

Task 1: complete (commit c1963cb, tests: `uv run pytest tests/test_commands_vim.py -q` → 13 fail → 14 passed; suite completa 231 passed + ruff limpio).

Task 2: complete (commit 40bcff7, tests: `uv run pytest tests/test_output_press.py -q` → 6 fail → 6 passed; suite completa 237 passed + ruff limpio). Ruling: spec D6 manda no-op si la capa no es uinput/pynput, pero el plan solo comprobaba `keys is None` — se implementa AMBAS: marca de clase `PRESS_CAPABLE` en UInputKeys/PynputKeys (chequeo previo con log claro) + try por token del plan — coste: atributo de clase nuevo en output.py y los fakes de test lo declaran (un test con un fake sin la marca sería no-op: documentado en el propio test partial).
