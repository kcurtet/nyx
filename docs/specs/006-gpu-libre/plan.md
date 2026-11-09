# Plan de implementación: modo GPU libre (spec 006)

> Ejecutar con la skill `executing-plans`, tarea a tarea. Pasos con checkbox `- [ ]`.

**Objetivo:** «Liberar GPU» en el tray descarga Whisper/TTS de memoria; el primer uso posterior recarga solo (self-healing); toda recarga exitosa apaga el modo.

**Arquitectura:** `Transcriber` y `Speaker` ganan `unload()` + carga serializada con su llave + self-healing en `transcribe()/segments()/say()` + callback `on_loaded`. app.py añade `state["gpu_free"]`, el comando de control `"gpu"` (con rechazo si hay trabajo en curso) y dispara la recarga en el keydown. El tray añade item toggle, estado de icono `free` y notifica los avisos del servicio.

**Stack:** Python 3.10+, pytest + monkeypatch, ruff. Sin dependencias nuevas.

**Spec:** `docs/specs/006-gpu-libre/spec.md` (incluye las decisiones del builder-check: recarga→sale del modo, self-healing, A5 rechaza).

## Restricciones globales

- Solo `nyx/stt.py`, `nyx/tts.py`, `nyx/app.py`, `nyx/tray.py`, `README.md` (solo si documenta el menú del tray) y tests.
- `uv run pytest -q tests` verde (Linux+Windows) y `uvx ruff check .` limpio.
- Tests SIEMPRE con fakes: monkeypatch de `Transcriber._load` y `Speaker.load`; nunca importar faster_whisper/ptts de verdad en CI.
- Sin persistencia del modo; sin config nueva.

## Foco de revisión

1. Hangs por `ready.wait()` sin nadie que cargue (el hallazgo BLOQUEA nº1 del check): todo camino que espera modelo pasa por el self-healing. Tests: T1/T2.
2. `Speaker.say()` esperando dentro de `self._lock` con TTS descargado (BLOQUEA nº2): el self-heal va ANTES del lock. Test: T2.
3. Toggle durante carga en curso → "libre con modelo cargado" (MINOR nº4): `load()` toma `self.lock` entera; `unload()` espera. Test: T1 (A10).
4. Gate de A5 insuficiente (`stt.lock.locked()` solo): combinación recording/sesión/speaking/busy/lock. Test: T3.
5. `state_of` pintando `free` como `busy`: precedencia. Test: T4.

---

### Tarea 1: `Transcriber` — unload, serialización, self-healing

**Ficheros:**
- Modificar: `nyx/stt.py`
- Test: `tests/test_gpu_libre.py` (nuevo)

**Interfaces:**
- Produce: `Transcriber.unload() -> None` — bajo `self.lock`: si modelo, `model=None, device=None, error=None, ready.clear(), gc.collect()`, log; idempotente.
- Produce: `Transcriber.on_loaded: Callable[[], None] | None = None` (atributo; app lo usará en T3; lo llama `load()` tras éxito).
- Modifica: `load()` — toma `self.lock` DURANTE TODA la carga (serializa con unload); guard anti-doble-carga (`_loading: threading.Event`: si ya cargando o modelo listo+ready → return temprano); al final con éxito → `if self.on_loaded: on_loaded()` (en hilo propio o directo, sin lock retenida).
- Modifica: `transcribe()` y `segments()` — tras `ready.wait()`, si `model is None and self.error is None` → self-heal: arrancar `load()` en hilo demonio y volver a esperar (bucle; el guard evita cargas múltiples); si `error` seteado → raise como hoy.

- [ ] **Paso 1: tests que fallan** (fake `_load`: monkeypatch `o_stt.Transcriber._load` con función que duerme con un `threading.Event` controlable y asigna `model` falso — un objeto con método `transcribe`):

```python
def test_unload_suelta_y_es_idempotente():          # A8
def test_transcribe_selfheal_descargado():           # model None + error None → dispara load y espera → transcribe OK (nunca raise "modelo no disponible: None")
def test_transcribe_raise_si_error_de_carga():       # error seteado → RuntimeError como hoy
def test_load_y_unload_se_serializan():              # A10: load lenta controlada; unload concurrente entra SOLO tras la asignación; estado final = libre
def test_guard_sin_doble_carga():                    # dos load() con la primera en marcha → una sola _load ejecutada
def test_on_loaded_se_llama_tras_exito():            # y NO tras carga fallida
```

- [ ] **Paso 2:** `uv run pytest tests/test_gpu_libre.py -v` → FAIL (AttributeError: `unload`/`on_loaded`).
- [ ] **Paso 3:** implementar en `stt.py`. Nota: `transcribe()` espera por `ready` ANTES de pedir `self.lock`; el self-heal nunca corre inline (siempre hilo demonio) — sin deadlocks.
- [ ] **Paso 4:** suite completa + ruff.
- [ ] **Paso 5:** commit `feat(stt): unload + carga serializada + self-healing (spec 006)`

### Tarea 2: `Speaker` — unload y self-healing en `say()`

**Ficheros:**
- Modificar: `nyx/tts.py`
- Test: `tests/test_gpu_libre.py`

**Interfaces:**
- Produce: `Speaker.unload() -> None` — bajo `self._lock`: `stop()`, `tts=None`, `ready.clear()`, log; idempotente.
- Produce: `Speaker.on_loaded: Callable[[], None] | None = None`.
- Modifica: `load()` — guard `_loading` (Event) anti-doble-carga; con éxito → `on_loaded`.
- Modifica: `say()` — ANTES de `with self._lock`: si `tts is None and not _loading` → hilo demonio con `load()`; el `ready.wait()` existente (ya dentro del lock) espera esa carga; si tras esperar `tts` sigue None (carga fallida) → `return False` (aviso en app, igual que hoy).

- [ ] **Paso 1: tests que fallan** (fake: monkeypatch `Speaker.load` — sí, el método entero: asigna `self.tts = _FakeTTS()` con `stream()` iterable y `ready.set()`; así se prueba la orquestación sin ptts):

```python
def test_speaker_unload_idempotente():
def test_say_con_tts_descargado_recarga_y_lee():     # A8-say: unload → say() → load disparado → habla (no hang, no False)
def test_say_sigue_fallando_limpio_si_carga_falla(): # load fake que deja tts None → say() False rápido
def test_speaker_on_loaded_tras_exito():
```

- [ ] **Paso 2:** FAIL esperado.
- [ ] **Paso 3:** implementar. Ojo: `speaking` property y `stop()` no cambian.
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(tts): Speaker.unload + recarga self-healing en say (spec 006)`

### Tarea 3: app.py — estado `gpu_free`, comando `"gpu"`, keydown, status

**Ficheros:**
- Modificar: `nyx/app.py` (start ~línea 71-78, status ~226-246, handlers ~334, on_ready)
- Test: `tests/test_gpu_libre.py`

**Interfaces:**
- Consume: T1/T2.
- Produce: `gpu_toggle(state: dict, stt, speaker, session: dict, notify) -> str` a NIVEL DE MÓDULO en app.py (D7; `notify` es un callable(str) que muestra el aviso — app le pasa `lambda m: ui.call(ui.error, m)`). Devuelve "" si alternó, o el mensaje de rechazo si hay trabajo en curso. Lógica: si va a libre → gate `state["recording"] or session["s"] or state["busy"] or stt.lock.locked() or (speaker and speaker.speaking)` → rechaza; si pasa → `stt.unload(); speaker.unload()` (si hay) + `state["gpu_free"]=True`. Si va a normal → `state["gpu_free"]=False` + hilo demonio `stt.load()` (precarga).
- Produce: en `on_ready`: `state["gpu_free"]=False`; `stt.on_loaded = speaker.on_loaded = lambda: state.__setitem__("gpu_free", False)` (D4b: toda recarga exitosa apaga el modo; thread-safe: dict assignment). En `start()` (keydown): si `stt.model is None` → hilo demonio `stt.load()`. En `status()`: añadir `"gpu_free": state["gpu_free"]`. En el dict del `ControlServer`: `"gpu": lambda _p="": gpu_toggle(...)`.

- [ ] **Paso 1: tests que fallan** (fakes: `stt`/`speaker` con `unload()`, `lock.locked()`, `speaking`, `model`, y `session={"s": None}`):

```python
def test_gpu_toggle_libera_y_rechaza_con_trabajo():  # A9+A5: idle → alterna a libre + unload de ambos; con recording/sesión/speaking/busy/lock → NO alterna y devuelve aviso
def test_gpu_toggle_salir_precarga():                # libre → normal: gpu_free False + load en hilo
def test_recarga_apaga_el_modo():                    # D4b: on_loaded de stt/speaker → gpu_free False
```

- [ ] **Paso 2:** FAIL esperado (ImportError de `gpu_toggle`).
- [ ] **Paso 3:** implementar + wiring. `lambda` del handler captura lo que necesite (state/stt/speaker/session/ui ya están en scope de `run()`).
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(app): comando de control gpu + estado gpu_free + recarga en keydown (spec 006)`

### Tarea 4: tray — item «Liberar GPU», estado `free`, avisos

**Ficheros:**
- Modificar: `nyx/tray.py` (COLORS/LABELS, state_of, menú, send)
- Test: `tests/test_transcribe.py` (ahí vive el test de `state_of`)

**Interfaces:**
- Consume: status `gpu_free`; comando `"gpu"`.
- Produce: `COLORS["free"]` (color distinto del gris idle — p. ej. naranja apagado) y `LABELS["free"] = "GPU libre"`. `state_of`: precedencia recording → speaking → **free** → busy → idle (`if st.get("gpu_free"): return "free"` antes del chequeo de `stt_ready`). Menú: `Item(gpu_label, lambda: send("gpu"), enabled=up)` con `gpu_label` dinámico según `gpu_free` del status («Liberar GPU» / «Usar GPU (carga modelo)»). `send()`: si `send_command` devuelve texto no vacío → `notify("nyx", texto)` (rechazos visibles).

- [ ] **Paso 1: tests que fallan** en `tests/test_transcribe.py`:

```python
def test_state_of_gpu_libre():        # {"gpu_free": True} → "free"; con recording + gpu_free → "recording" (transitorio al salir); sin gpu_free igual que hoy
def test_state_of_free_gana_a_busy(): # {"gpu_free": True, "stt_ready": False} → "free" (no "busy")
```

- [ ] **Paso 2:** FAIL (KeyError/LABELS).
- [ ] **Paso 3:** implementar (docstring de colores del tray al día).
- [ ] **Paso 4:** suite + ruff.
- [ ] **Paso 5:** commit `feat(tray): toggle Liberar GPU + estado de icono free (spec 006)`

### Tarea 5: README (si procede) y verificación final

- [ ] **Paso 1:** `grep -n "tray\|bandeja\|icono" README.md` — si documenta el menú del tray, añadir fila/línea de «Liberar GPU»; si no, no tocar.
- [ ] **Paso 2:** `uv run pytest -q tests && uvx ruff check .` verde.
- [ ] **Paso 3:** commit final si hubo docs (`docs: …`).

## Verificación final (manual, PENDIENTE para el humano — NO ejecutar)

Servicio en marcha → toggle «Liberar GPU» en el tray → `nvidia-smi --query-compute-apps`: VRAM de nyx de ~2.2 GiB a <300 MiB; icono nuevo estado; dictar → «cargando modelo…» → texto; tray vuelve a normal.

## Notas para el implementador

- No rediseñes `Transcriber`/`Speaker` más allá de lo dicho: llaves existentes, eventos existentes.
- `clean-tests`: un concepto por test; español como el resto.
- Conflictos con el plan → ruling al ledger (`docs/specs/006-gpu-libre/progress.md`), la spec manda.
