# Ledger — plan: docs/specs/006-gpu-libre/plan.md

## Progreso

- Task 1: complete (commit b07920e, tests: `uv run pytest tests/test_gpu_libre.py -q` → 7 passed; suite 203 passed + ruff limpio). Nota menor: `load()` con éxito borra `self.error` de un intento anterior (necesario para que el self-heal no levante el error viejo tras un reintento exitoso).
- Task 2: complete (commit 0721647, suite 208 passed + ruff limpio, exit code verificado — un `| tail` anterior se tragó un hang, corregido antes de cerrar; ver Ruling 3).
- Task 3: complete (commit 0db160c, tests: `-k "gpu_toggle or recarga_apaga"` → 3 passed tras RED por ImportError; suite 211 passed + ruff limpio).
- Task 4: complete (commit 5a5450e, tests: `-k "gpu_libre or gana_a"` → 2 passed tras RED por AssertionError; suite 213 passed + ruff limpio).
- Task 5: complete (commit 73821af — README sí documenta el menú/colores del tray (línea «Icono en la bandeja»): añadidos color ámbar, ítem y párrafo «Liberar GPU»; suite 213 passed + ruff limpio).

## Rulings

1. **hotkey.py: `"gpu"` en SYNC_COMMANDS (1 línea)** — la restricción de ficheros del encargo omitía `nyx/hotkey.py`, pero la spec lo permite expresamente y el plan (T4: «send(): si send_command devuelve texto no vacío → notify») exige que la respuesta del handler llegue al tray: sin SYNC el canal responde "ok" siempre (y un notify genérico sobre texto no vacío notificaría "ok" en cada comando). Se añadió `report=True` solo al ítem GPU. Coste si me equivoco: revert de 1 línea; el rechazo de A5 seguiría visible por la burbuja del servicio (`ui.error`), perdiendo solo la notificación del tray.
2. **Speaker: espera FUERA del lock + load bajo llave toda la carga** — el plan (T2) decía «el ready.wait() existente (ya dentro del lock) espera esa carga», pero eso es un deadlock con un `load()` que toma `_lock` (D3: «unload() análogo a D2 (con su propio lock)»). La spec manda: D3 dice «arrancar load() (guard) y esperar ANTES de tomar el lock de reproducción». Implementado así. Coste: en el camino «voz ya cargada» el comportamiento es idéntico (ready ya seteado, ni espera); tras unload nada está sonando, así que retrasar `stop()` hasta después de la espera no cambia nada audible.
3. **say() reintenta UNA vez por llamada (if, no while) + `ready.clear()` al inicio de `load()` (stt y tts)** — con fallo persistente, un bucle giraba en spin spawneando hilos (hang real: `test_say_sigue_fallando_limpio_si_carga_falla` colgó la suite; detectado porque el exit code de pytest se verificaba a mano). El `ready.clear()` al arrancar cada carga caduca el veredicto anterior y elimina el estado transitorio «ready set + modelo None + nadie cargando» (nadie espera con un veredicto viejo). Coste: si la recarga falla, `say()` devuelve False (como hoy) y el reintento real cae en la siguiente llamada — nunca hang; comportamiento de fallo idéntico al actual.
4. **Gate de A5 = rechazo también con carga en marcha; la serialización por llave queda como red de seguridad (TOCTOU)** — D2 describía «el toggle durante una carga en curso espera a que acabe y luego descarga», pero `stt.lock.locked()` (cierto durante TODA la carga) forma parte del gate de A5/D1, así que por el handler el toggle RECHAZA si hay carga en curso (coherente con A5: «RECHAZA con aviso inmediato»). El «recheck bajo llave dentro de unload()» se materializa como: releer el estado con la llave tomada (idempotencia) + la llave compartida carga/unload/inferencia, que garantiza el invariante «nunca modelo cargado con gpu_free=true» ante el hueco gate→unload (una inferencia que se cuela acaba antes de que unload descargue; un dictado que se cuela lo cubre el self-healing, caso límite explícito de la spec). Coste: con una carga en marcha el usuario ve «espera a que termine» en vez de un toggle que espera en silencio — un reintento después funciona; cero riesgo de estado mentiroso.
5. **`_link_gpu_free()` como función de módulo (espíritu D7)** — el plan cableaba `on_loaded` inline en `on_ready`, pero `on_ready` no corre en la suite y D4b quedaría sin test unitario. Coste: ninguno (misma semántica; se llama justo tras crear `state`).
6. **app usa `stt._spawn_load()` para keydown (D4) y precarga de salida** — en vez de `threading.Thread(target=stt.load)` crudo: un fallo de carga en hilo crudo imprime traceback al log sin reporting útil; `_spawn_load` (hilo demonio silencioso, guard incluido) ya existía para exactamente eso. Coste: acoplamiento a un método «privado» del mismo paquete (los fakes del test lo implementan).

## Minors diferidos

- Aviso por voz al liberar («GPU libre»): la spec lo dejó en default «solo burbuja/notificación» — no implementado, conforme.
- Precarga de salida carga solo Whisper (el TTS ya es lazy bajo demanda): opción que la spec deja al builder; `say()` lo recarga solo si hace falta.
- `status()` no expone campo «cargando» propio (no pedido): «cargando modelo…» se infiere de `stt_ready=false` como hoy.

## PENDIENTE (humano) — verificación final manual, NO ejecutada

Servicio real en marcha → «Liberar GPU» en el tray → `nvidia-smi --query-compute-apps`: VRAM de nyx de ~2.2 GiB a <300 MiB (A1); icono ámbar «GPU libre» (A7); dictar → «cargando modelo…» → texto, segundo dictado sin espera, tray vuelve a normal (A2); «léeme esto» recarga la voz y lee (A3); fichero/sesión recargan y desactivan el modo (A4); toggle con trabajo en curso → aviso (A5); reinicio del servicio carga como siempre (A6).
