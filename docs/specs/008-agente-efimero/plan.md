# Plan de implementación: agente efímero (spec 008)

> Ejecutar con la skill `executing-plans`, tarea a tarea. Pasos con checkbox `- [ ]`.

**Objetivo:** `backend = "efimero"` — cada orden arranca un `pi -p` con memoria en fichero (`--continue`), lee la respuesta en voz alta y muere. Rotación de sesión diaria + botón «Sesión nueva» en el tray.

**Arquitectura:** `EfimeroBackend` hermano de `PiRpcBackend` en orders.py (subprocess one-shot, callback `on_say`); `pi_args_for` gana `voice=`; comando de control `"session"`; ítem de tray; rama doctor; supervisor no-op por contrato (status nunca None).

**Stack:** Python 3.10+, pytest + monkeypatch, ruff. Sin dependencias nuevas.

**Spec:** `docs/specs/008-agente-efimero/spec.md` (decisiones humanas + del builder-check ya integradas)

## Restricciones globales

- Solo `nyx/orders.py`, `nyx/app.py`, `nyx/hotkey.py` (SYNC), `nyx/tray.py`, `nyx/doctor.py`, `nyx/config.py`, `config.example.toml`, `README.md` y tests.
- `uv run pytest -q tests` verde (Linux+Windows) y `uvx ruff check .` limpio.
- Tests del agente SIEMPRE con `pi` falso (patrón `FAKE_PI` de tests/test_orders.py: script ejecutable que loggea args y responde); Popen/which fakeados donde toque — nunca un pi real en CI.

## Foco de revisión

1. Doble voz: el spawn efímero NO carga voice.ts (`pi_args_for(…, voice=False)`); la lee el backend vía `on_say`.
2. Memoria rota por cwd: Popen con `cwd=Path.home()` fijo (pi agrupa sesiones por cwd).
3. Backend None para siempre si falta `name = "efimero"` + entrada en el dict de `_pick`.
4. Supervisor lanzando cosas con efimero: `status()` NUNCA devuelve None.
5. Spawn fresco = solo omitir `--continue` (nada de borrar ficheros).

---

### Tarea 1: `pi_args_for(voice=)` + `EfimeroBackend` núcleo

**Ficheros:**
- Modificar: `nyx/orders.py`
- Test: `tests/test_orders.py` (junto a `test_backend_pi_rpc`)

**Interfaces:**
- Modifica: `pi_args_for(cfg, with_herdr: bool = True, voice: bool = True) -> list[str]` — `voice=False` omite `["-e", str(AGENT_DIR / "voice.ts")]`.
- Produce: `class EfimeroBackend` — `name = "efimero"`; `__init__(cfg, on_say: Callable | None = None)`; `status() -> "working"|"idle"|None igual que PiRpcBackend PERO "idle" con proceso muerto (nunca None salvo error de construcción); `send(order)` → lock: si vivo → `(False, "…ocupada, espera…")`; si no → `Popen(["pi","-p","--",order,"--session-dir",str(dir),"--continue"? , *pi_args_for(cfg, with_herdr=False, voice=False)], cwd=Path.home(), stdout=PIPE, stderr=log)` — el `--continue` según D7 (T3 lo hace condicional; aquí siempre) — hilo lector: `out, _ = proc.communicate()` → `on_say(out.strip() or MSG_ERROR, brief=True)` si `proc.returncode == 0 or out.strip()` else `on_say(MSG_ERROR, brief=True)`; `launch() -> (True, "…lista; las órdenes la arrancan. Dile: «Nyx, …»")`; `stop()` → terminate si vive.

- [ ] **Paso 1: tests que fallan** (fake `pi` ejecutable estilo `FAKE_PI` que escribe sus argv a un fichero y responde "hecho"):

```python
def test_efimero_arranca_y_habla():        # A1: Popen con -p, --, orden, --continue, session-dir, cwd=home, SIN voice.ts en argv
def test_efimero_rechaza_ocupada():        # A2: dos sends con proceso vivo → segundo (False, "ocupada") y un solo spawn
def test_efimero_error_sin_salida():       # A3: fake exit 1 sin stdout → on_say recibe error, estado vuelve a idle
def test_efimero_texto_parcial_se_lee():   # exit 1 CON stdout → se lee el texto
def test_efimero_mismo_session_dir():      # A4: dos órdenes → mismo --session-dir y mismo cwd, segunda con --continue
def test_efimero_status_y_stop():          # A6/A8: working con vivo, idle tras morir; stop() lo mata
```

- [ ] **Paso 2:** FAIL esperado (no existe la clase).
- [ ] **Paso 3: implementar** (usa el lock y STATE_DIR como PiRpcBackend; session dir = el MISMO `STATE_DIR/f"{agent}-sessions"`).
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(orders): backend efimero — pi one-shot por orden con voz y memoria en fichero`

### Tarea 2: integración — choose_backend, _pick, supervisor, doctor

**Ficheros:**
- Modificar: `nyx/orders.py` (choose_backend, `Orchestrator._pick` dict, docstring del módulo), `nyx/doctor.py` (`_doctor_orders`)
- Test: `tests/test_orders.py`

**Interfaces:**
- `choose_backend`: `want == "efimero"` → `("efimero", "")` (requiere pi, como los demás).
- `_pick`: dict `"efimero": EfimeroBackend` — construido con el callback `on_say` (ver D2: `Orchestrator` gana atributo/param `on_say=None` que app asigna tras crearlo).
- doctor: rama `kind == "efimero"` → `r.ok("pi efímero", "arranca con cada orden; memoria en el fichero de sesión")` y el status de siempre (idle/working).

- [ ] **Paso 1: tests que fallan**:

```python
def test_choose_backend_efimero():         # A7: ("efimero",""); auto/herdr/pi intactos
def test_pick_registra_efimero():          # Orchestrator({**CFG,"backend":"efimero"}).backend es EfimeroBackend
def test_supervisor_no_lanza_con_efimero():# A5: un tick del loop (time.sleep patcheado o tick extraído) → cero Popen
def test_doctor_rama_efimero():            # salida contiene "pi efímero", no "en marcha (idle)" residente-mentiroso
```

- [ ] **Paso 2:** FAIL esperado.
- [ ] **Paso 3: implementar** (para A5: extraer el cuerpo del loop a `Orchestrator._supervise_once()` es opción limpia — criterio del builder).
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(orders,doctor): efimero en choose_backend/_pick/supervisor y doctor honesto`

### Tarea 3: rotación de sesión (diaria + botón tray)

**Ficheros:**
- Modificar: `nyx/orders.py` (EfimeroBackend: `_fresh` + chequeo diario), `nyx/app.py` (handler `"session"`), `nyx/hotkey.py` (`"session"` en SYNC_COMMANDS), `nyx/tray.py` (ítem)
- Test: `tests/test_orders.py`

**Interfaces:**
- `EfimeroBackend`: `fresh_next: bool`; `_newest_is_today() -> bool` (fichero más reciente del session-dir con mtime de HOY — `max(p.stat().st_mtime for p in dir.glob("*.jsonl"))` comparado con la medianoche local); en `send`: spawn fresco (SIN `--continue`) si `fresh_next or not _newest_is_today()`; al spawnear fresco → reset de `fresh_next`. `new_session() -> str` → si vivo: "está trabajando, espera"; si no: `fresh_next = True`, `on_say("Sesión nueva.", brief=True)` si hay callback, devuelve "".
- app.py: handler `"session": lambda _p="": orch.new_session()` (la respuesta viaja al tray por SYNC).
- tray.py: dentro del menú Nyx: `Item("Sesión nueva", lambda: send("session"), visible=lambda _i=None: (current["status"] or {}).get("nyx", {}).get("backend") == "efimero")`.

- [ ] **Paso 1: tests que fallan**:

```python
def test_rotacion_diaria():                # A9: sesión de ayer en el dir → primer send SIN --continue; siguiente CON
def test_sesion_nueva_por_comando():       # A10: idle → new_session() marca → próximo send sin --continue + "Sesión nueva."
def test_sesion_nueva_rechaza_trabajando():# A10b: working → "está trabajando", flag sin marcar
def test_tray_item_solo_con_efimero():     # A11: visible con backend efimero, oculto con otros
```

- [ ] **Paso 2:** FAIL esperado.
- [ ] **Paso 3: implementar.**
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(orders,app,tray): rotación de sesión — diaria y botón «Sesión nueva» (efimero)`

### Tarea 4: config, docs y verificación final

**Ficheros:**
- Modificar: `nyx/config.py` (comentario de `backend`), `config.example.toml` (sección `[orders]` con `# backend = "efimero"`), `README.md`

- [ ] **Paso 1:** comentario/doc al día: tres backends + auto; nota README de la rotación diaria y el botón.
- [ ] **Paso 2:** `uv run pytest -q tests && uvx ruff check .`
- [ ] **Paso 3:** commit `docs(config,readme): backend efimero y rotación de sesión`

## Verificación final (manual, PENDIENTE para el humano — NO ejecutar)

`backend = "efimero"` en config → reiniciar servicio → dictar «Nyx, ¿qué branch tengo?» → segundos de silencio (pi arranca) → respuesta en voz alta → `pgrep -f "pi -p"` vacío (murió) → orden siguiente recuerda la anterior → botón «Sesión nueva» → la siguiente orden no recuerda nada → mañana, primera orden = memoria del día, no de ayer.

## Notas para el implementador

- NO toques PiRpcBackend/HerdrBackend salvo el parámetro `voice=` en pi_args_for.
- MSG de voz al gusto del repo, cortos.
- Conflictos → ruling al ledger (`docs/specs/008-agente-efimero/progress.md`); la spec manda.
