# Ledger — plan: docs/specs/005-herdr-sin-terminal/plan.md

## Baseline

- `uv run pytest -q tests` → 186 passed (rama hd/impl-005, commit 5698ee0).

## Task 1: complete

- Commit e892988. Tests: `uv run pytest tests/test_orders.py -k herdr_server_running -v` → primero FAIL (AttributeError, como el plan), luego PASS; suite 186→188 passed.
- `uvx ruff check .` limpio.

## Task 2: complete

- Commit (ver abajo). Tests: `-k "error_json or servidor_caido"` → FAIL (rc 0; 'unknown' != None) → PASS; suite 190 passed.
- Ruling: el código literal del plan para `test_herdr_status_none_con_servidor_caido` fakeaba `_herdr` con rc 1, que pasa igual antes que después (no puede fallar); su propio comentario y su Expected dicen que el bug es rc 0 + error JSON → "unknown". Reescrito para pasar por el `_herdr` REAL (subprocess.run fakeado, rc 0 + cuerpo de error), que hoy devuelve "unknown" y tras D4 None. Coste si me equivoco: el test de regresión queda más acoplado a la implementación real de `_herdr` (menos aislado), pero es justo lo que D4 repara.

## Task 3: complete

- Commit (siguiente hash). Tests: `-k ensure -v` → FAIL (AttributeError, como el plan) → PASS (3); suite 193 passed.
- `uvx ruff check .` limpio. Sin spawn real en ningún test (D3b): Popen/_herdr_server_running/time.* fakeados.
- Nota: al anclar la edición de T2 borré sin querer `test_los_comandos_citados_empiezan_por_nyx`; restaurado y commit de T2 amndado (sin push, rama propia). Suite re-cuentada: 190 tras T2.
- Desviación menor vs plan: assert del comando spawn comparado como lista (`[["/usr/bin/herdr", "server"]]`) porque Popen recibe la lista; el plan lo escribía como tupla. Mismo contrato.
