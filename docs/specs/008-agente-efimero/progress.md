# Ledger — plan: docs/specs/008-agente-efimero/plan.md

Formato: "Task N: complete (commits, tests → resultado)". Rulings: "Ruling: <qué> — <porqué> — <coste>".

## Task 1: pi_args_for(voice=) + EfimeroBackend núcleo

Complete (b86f367, 7 tests nuevos: efimero_arranca_y_habla / rechaza_ocupada / error_sin_salida /
texto_parcial_se_lee / mismo_session_dir / status_y_stop / args_voice_false_omite_voice_ts →
261 passed, ruff limpio).

Ruling: argv con opciones ANTES de «--» (plan/spec D1 las ponían tras la orden) — verificado
contra pi 1.5.2: todo lo que sigue a «--» es posicional para su CLI (`pi -p -- "hola" --version`
ejecuta el prompt, no imprime la versión) — coste: ninguno; «--» sigue inmediatamente antes
de la orden (protege órdenes que empiezan por «-») y los criterios A1/A4 (presencia de
--continue, session-dir compartido, cwd pinneado) se cumplen igual.
Ruling: `stopping` en stop() — sin él, apagar el servicio con una orden en marcha daría voz
de error (el lector ve exit != 0 tras el terminate) — coste: 3 líneas.
Ruling: tests leen el log de spawns con espera (_wait_spawns) — el pi falso corre en su
propio proceso y el assert inmediato tenía una carrera — coste: helper de 7 líneas.

## Task 2: integración — choose_backend, _pick, supervisor, doctor

Pendiente.

## Task 3: rotación de sesión (diaria + botón tray)

Pendiente.

## Task 4: config, docs y verificación final

Pendiente.

## Verificación manual (PENDIENTE para el humano — NO ejecutada por el implementador)

`backend = "efimero"` en config → reiniciar servicio → dictar «Nyx, ¿qué branch tengo?» →
respuesta en voz alta → `pgrep -f "pi -p"` vacío → orden siguiente recuerda → botón
«Sesión nueva» → siguiente orden sin memoria → mañana, primera orden = sesión del día.
