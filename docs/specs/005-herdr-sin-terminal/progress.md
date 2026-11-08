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

## Task 4: complete

- Commit (siguiente hash). Tests: `-k "eleccion or explicito or sin_instalar"` → eleccion y explicito FAIL (choose_backend ignora el ensure falso, como el plan), sin_instalar ya PASABA (la rama "no instalado" existía: es test de regresión, no comportamiento nuevo). Tras implementar: 3 PASS; suite 195 passed, ruff limpio.
- Desviación menor: en la fase roja, `test_eleccion_de_backend` alcanzó `herdr_available()` REAL (FileNotFoundError en `/usr/bin/herdr` falso). Solo lectura (`status --json`), nunca spawn; desaparece al implementar.

## Task 5: complete

- Commit (siguiente hash). Tests: `-k doctor_avisa` → FAIL (AttributeError: `_doctor_orders`) → PASS; suite 196 passed, ruff limpio.
- Elección de implementación (el plan dejaba el "cómo" abierto): sección de doctor extraída a `_doctor_orders(r, oc)` para llamarla aislada en test (con choose_backend/_herdr/_SERVER_STARTED_BY_NYX fakeados, D3b: cero subprocess reales). La salida de doctor() es idéntica línea a línea.

## Verificación final

- `uv run pytest -q tests` → 196 passed · `uvx ruff check .` → All checks passed! (rama hd/impl-005, 5 commits).
- PENDIENTE (humano): demo manual con servidor real — `herdr server stop` → `systemctl --user restart nyx` → esperar ~25 s → `herdr workspace list` muestra el workspace con el servidor arrancado por nyx; `pgrep -af "herdr server"` sin TTY. NO ejecutada (mataría los paneles vivos del usuario).
