# 006 — modo GPU libre: liberar la VRAM desde el tray

## Contexto

Al jugar, el modelo Whisper de nyx (large-v3-turbo float16) mantiene ~2.2 GiB de VRAM residentes (verificado con `nvidia-smi`: el proceso del servicio retiene 2194 MiB). El humano quiere liberarlos con un clic en el tray, sin cerrar nyx.

Estado actual: `Transcriber` (nyx/stt.py) carga el modelo al arrancar el servicio y no tiene `unload`; el TTS (`Speaker`, phonon) carga bajo demanda; el tray habla con el servicio por el canal de control (`ControlServer` en nyx/hotkey.py: comandos `start|stop|toggle|cancel|read|hush|ping|say`); el icono del tray pinta un micrófono sobre un círculo cuyo color viene de `COLORS[state]`.

Decisiones del humano (sesión 2026-11-08):

- El servicio puede seguir vivo; lo importante es que **el modelo no ocupe la gráfica**.
- **Reactivación: auto-recarga al dictar** — mantienes Ctrl derecho, el modelo recarga mientras hablas, y al soltar transcribe (espera si aún carga).
- **Alcance: todo lo que nyx retenga en GPU** (Whisper y TTS si ocupa).
- **No persiste**: un reinicio del servicio vuelve a cargar el modelo, como hoy.

Decisiones del orquestador tras el builder-check (pre-aprobadas por el humano, sesión 2026-11-08):

- **Toda recarga exitosa sale del modo**: `gpu_free → false` cuando dictado/fichero/sesión/lectura recargan. Invariante: `gpu_free = true` ⇔ modelos no residentes (status y tray nunca mienten).
- **Self-healing**: quien recarga son los propios `Transcriber`/`Speaker` desde dentro (`transcribe`/`segments`/`say` arrancan `load()` si el modelo falta y no hay carga en marcha). El keydown del dictado solo adelanta el arranque.
- **A5 rechaza** (no espera): toggle a libre con trabajo en curso → aviso inmediato, reintentar luego.

## Objetivo

«Liberar GPU» en el tray deja la VRAM de nyx casi a cero; el primer dictado posterior la recarga solo, con el aviso «cargando modelo…» que ya existe.

## Objetivos

1. Modo **GPU libre** en el servicio: descarga Whisper (y TTS cargado) de memoria; el servicio, el tray y la configuración siguen vivos.
2. Toggle en el tray: entra al modo (item «Liberar GPU») y sale (recarga el modelo en segundo plano); icono y título reflejan el estado.
3. Dictar en modo GPU libre arranca la recarga automáticamente al pulsar la tecla (no al soltar), y la transcripción espera a que el modelo esté listo.
4. Caminos que comparten el modelo (transcribir fichero, grabar sesión, «léeme esto») también funcionan en modo libre: recargan lo que necesiten.

## No-objetivos

- Descargar el modelo de visión de Ollama (nyx look): ya se autogestiona con `keep_alive`.
- Persistir el modo entre reinicios del servicio (decisión explícita del humano).
- Config nueva: el modo es runtime, no configuración.
- Ahorro configurable de RAM u opciones por modelo.

## Decisiones de implementación

**D1 — Estado y control**: `state["gpu_free"]: bool` en app.py. Comando de control `"gpu"` (toggle) en el `ControlServer`; el status que ya lee el tray añade `"gpu_free"`. El toggle a "libre" con trabajo en curso **rechaza con aviso** (burbuja/notificación "espera a que termine"); la señal de "en curso" es la combinación `state["recording"]` · sesión activa · `speaker.speaking` · `state["busy"]` — NO basta `stt.lock.locked()` (la grabación entre keydown y release no toma la llave, y una sesión la suelta entre trozos de 25 s) — más un recheck bajo llave dentro de `unload()` (TOCTOU).

**D2 — `Transcriber.unload()` y serialización** (nyx/stt.py): `load()` y `unload()` se serializan con `self.lock` TOMADO DURANTE TODA la carga (hoy `load()` no lo toma): así el toggle durante una carga en curso espera a que acabe y luego descarga — nunca queda "modelo cargado con gpu_free=true". `unload()`: con `model is not None`: `model = None`, `device = None`, `error = None`, `ready.clear()`, `gc.collect()`, log. Idempotente. **Self-healing**: `transcribe()`/`segments()`, si `model is None and error is None` (descargado, no fallo de carga), arrancan `load()` en hilo demonio (guard contra doble carga) y esperan; si `error` está seteado, `raise` como hoy.

**D3 — `Speaker.unload()` y recarga real** (nyx/tts.py): hoy la recarga NO es lazy — `say()` hace `ready.wait()` y devuelve False si `tts is None`; quien carga es `on_ready` una vez. La spec exige: `unload()` análogo a D2 (con su propio lock) + **self-healing en `say()`**: si `tts is None` tras unload → arrancar `load()` (guard) y esperar ANTES de tomar el lock de reproducción; el camino "cargando voz…" de app.py ya avisa. Si la recarga falla → retorno False limpio (aviso en app.py), nunca hang.

**D4 — Keydown adelanta la carga**: en el keydown del dictado (app.py, donde `state["recording"] = True`), si `stt.model is None` → hilo demonio con `stt.load()` (el guard de D2 evita duplicar). Es una optimización (la carga corre mientras hablas); la corrección la garantiza el self-healing de D2.

**D4b — Toda recarga exitosa sale del modo**: cuando `load()` completa (desde cualquier camino) y el modo estaba libre, `gpu_free → false` (el handler/estado lo refleja en el próximo status; el tray re-etiqueta).

**D5 — Tray** (nyx/tray.py): item toggle con label dinámico — «Liberar GPU» en normal, «Usar GPU (carga modelo)» en libre — que envía `"gpu"`. Estado de icono nuevo `"free"`: color DISTINTO del gris de idle (p. ej. naranja apagado; a criterio del builder), entrada nueva en `COLORS` y `LABELS` (sin KeyError en `title_text`), y `state_of()` evalúa `gpu_free` ANTES que "modelo no listo" (si no, free se pintaría azul "busy"). El menú en modo libre no deshabilita nada: todo recarga solo (Objetivo 4).

**D6 — No persiste**: nada que guardar; el arranque del servicio carga el modelo igual que hoy.

**D7 — Testabilidad del comando**: los handlers del ControlServer son closures dentro de `app.run()`; para el test unitario del comando `"gpu"` (A9) se extrae lo mínimo testable (p. ej. fábrica de handlers a nivel de módulo o función `_gpu_toggle(state, stt, speaker)`), sin cambiar comportamiento.

## Restricciones

- Solo `nyx/stt.py`, `nyx/tts.py`, `nyx/app.py`, `nyx/hotkey.py`, `nyx/tray.py` y tests.
- Suite verde (Linux + Windows) y ruff; sin dependencias nuevas.
- En Windows (sin CUDA) el modo sigue existiendo: libera RAM; mismo código.

## Criterios de aceptación (Given/When/Then)

- **A1** G: modo GPU libre activo. W: `nvidia-smi --query-compute-apps`. T: la VRAM del proceso de nyx cae de ~2.2 GiB a <300 MiB (criterio manual; CI va con fakes).
- **A2** G: modo GPU libre. W: mantienes Ctrl derecho, hablas, sueltas. T: burbuja «cargando modelo…» y el texto aparece (el modelo cargó al pulsar, no al soltar); un segundo dictado no espera; y el modo quedó DESCONECTADO (tray vuelve a estado normal).
- **A3** G: modo GPU libre. W: «léeme esto» (o Ctrl+0). T: recarga la voz en segundo plano, lee, y el modo queda desactivado; si la recarga falla, aviso claro, no silencio ni hang.
- **A4** G: modo GPU libre. W: transcribir fichero / grabar sesión. T: recargan el modelo (self-healing en `segments()`), funcionan, y el modo queda desactivado.
- **A5** G: transcripción, sesión o lectura en curso. W: toggle a GPU libre. T: RECHAZA con aviso inmediato («espera a que termine»); nunca descarga el modelo bajo trabajo activo — ni en el hueco entre trozos de una sesión.
- **A6** G: modo GPU libre, se reinicia el servicio. W: arranque. T: el modelo carga como hoy (no persiste).
- **A7** G: toggle en el tray. W: entra y sale del modo. T: label del item cambia, icono de estado `free` (color distinto del idle), el status expone `gpu_free`.
- **A8** (unit) G: `unload()` llamado. T: `model is None`, `ready` limpio, segunda llamada no-op. G: dos pulsaciones de tecla con modelo descargado. T: una sola `load()` en marcha (guard). G: `transcribe()`/`segments()` con `model None` y `error None`. T: disparan la carga y esperan (no raise «modelo no disponible: None»). G: `say()` con TTS descargado. T: dispara la carga y lee.
- **A9** (unit) G: comando `"gpu"` al ControlServer (handlers extraídos según D7). T: `state["gpu_free"]` alterna, el status lo refleja, y con trabajo en curso rechaza sin alternar.
- **A10** (unit) G: `load()` en marcha. W: `unload()` concurrente. T: se serializan (llave compartida): nunca queda modelo cargado con el modo libre.

## Casos límite

- Dictar justo tras liberar (race unload↔load): la llave compartida y el guard lo serializan; como mucho, el dictado espera (self-healing).
- Release del dictado mientras llega el unload: `transcribe()` con `error None` dispara la carga (self-healing) en vez de raise.
- Toggle rápido libre↔normal: el guard evita cargas dobles; el modo final es el del último toggle.
- Recarga con la VRAM llena por el juego: el fallback CUDA→CPU existente en `load()` responde (y el modo se apaga igualmente).
- Transcripción larga de fichero en curso + toggle: caso A5 (rechaza).
- `say()` con TTS descargado y recarga que falla (modelo corrupto): aviso, no crash, no hang.
- Servicio en CPU (sin CUDA): el modo sigue disponible (libera RAM); mismos tests con fakes.

## Qué queda a criterio del builder

- Color exacto del estado `"free"` y textos finales del item (español, tono del repo).
- Cómo implementar el guard de carga (flag `_loading` + lock existente, o un lock propio).
- Si el toggle de salida recarga Whisper y TTS a la vez o solo Whisper (TTS ya es lazy).
- Nombres de tests, siguiendo el estilo de `tests/test_orders.py`.

## Preguntas abiertas

- ¿Aviso por voz al liberar («GPU libre»)? Default: solo burbuja/notificación del tray, sin TTS (coherente: acabamos de descargarlo).
