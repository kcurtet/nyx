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

Complete (48e8f5e, 4 tests nuevos: choose_backend_efimero / pick_registra_efimero /
supervisor_no_lanza_con_efimero / doctor_rama_efimero → 265 passed, ruff limpio).

Ruling: supervisor — extraído el cuerpo del ciclo a `Orchestrator._supervise_once()`
(tri-estado True/False/None para conservar el backoff exacto de hoy) en vez de patchear
time.sleep en el test — coste: refactor de 15 líneas, loop intacto semánticamente.

## Task 3: rotación de sesión (diaria + botón tray)

Complete (7a32b41, 5 tests nuevos: rotacion_diaria / sesion_nueva_por_comando /
sesion_nueva_rechaza_trabajando / sesion_nueva_orquestador_y_sync / tray_item_solo_con_efimero
→ 270 passed, ruff limpio).

Ruling: `_newest_is_today()` devuelve True con el session-dir VACÍO — el snippet del plan
(`max(...)`) dejaría el caso sin definir y con False el backend jamás pasaría --continue con
un pi de verdad recién estrenado; verificado en el código de pi 1.5.2 (continueRecent:
"Continue the most recent session, or create new if none") que --continue con dir vacío
arranca sesión nueva, así que True es equivalente en comportamiento real y testeable con
pi falso — coste: ninguno.

## Task 4: config, docs y verificación final

Complete (commit abajo): comentario de `backend` en config.py (tres backends + auto),
sección `[orders]` nueva en nyx/config.example.toml con `# backend = "efimero"`, README
(dónde vive + memoria en fichero + rotación diaria + botón) → 270 passed, ruff limpio,
example sigue siendo TOML válido, default `auto` intacto.

Nota: `config.example.toml` del plan = `nyx/config.example.toml` (el único que existe en
el repo; el que copia `nyx config`), no un fichero nuevo en la raíz.
Smoke extra (sin test): `nyx agent` con efimero imprime el texto de launch() y sale 0 (D5
unificado por construcción: launch() de orders.py usa backend.launch()).

### Commits de la rama

1. 5726a43 feat(orders): backend efimero — pi one-shot por orden con voz y memoria en fichero
2. 163b550 feat(orders,doctor): efimero en choose_backend/_pick/supervisor y doctor honesto
3. f08c650 feat(orders,app,tray): rotación de sesión — diaria y botón «Sesión nueva» (efimero)
4. 45c31b0 docs(config,readme): backend efimero y rotación de sesión

## Verificación manual (PENDIENTE para el humano — NO ejecutada por el implementador)

`backend = "efimero"` en config → reiniciar servicio → dictar «Nyx, ¿qué branch tengo?» →
respuesta en voz alta → `pgrep -f "pi -p"` vacío → orden siguiente recuerda → botón
«Sesión nueva» → siguiente orden sin memoria → mañana, primera orden = sesión del día.
