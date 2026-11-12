# 008 — agente efímero: pi solo existe mientras trabaja

## Contexto

Tras 005/006/007, el humano reporta: "es molesto tener siempre un agente pi encendido dentro del herdr; sería mejor que ejecutara el pi solo cuando es necesario y que tenga la memoria en un archivo o algo así".

Hoy `backend = "herdr"` mantiene un workspace con pi residente (visible), y `backend = "pi"` un pi `--mode rpc` dentro del servicio (invisible pero encendido siempre). Ambos arrancan al iniciar el servicio (supervisor) y su conversación ya persiste en fichero (`--session-dir` + `--continue`).

Lo que quiere: **nada encendido**. La orden por voz ARRANCA pi, pi trabaja esa orden, responde por voz, y muere. La memoria vive en el fichero de sesión: la siguiente orden arranca pi con `--continue` y sigue la misma conversación.

Decisiones del humano (sesión 2026-11-09): **muere al terminar** (sin idle timeout) · respuesta **solo por voz** (como hoy voice.ts: `nyx say --brief`) · orden nueva mientras trabaja: **rechazar con aviso** ("ocupada, espera"), sin cola.

Decisiones del orquestador tras el builder-check (verificado contra pi 1.5.2: `-p` imprime solo la respuesta final en stdout, errores → stderr + exit != 0; stop length → texto parcial en stdout + exit != 0; las opciones globales funcionan igual en -p): doctor.py ENTRA en el alcance (una rama efimero de ~3 líneas: sin ella imprime «herdr + pi · en marcha», mentira); pi_args_for gana parámetro `voice=True` y efimero lo pasa False (con voice.ts cargada habría doble voz: ella llama `nyx say --brief` Y el backend habla); Popen con `cwd=Path.home()` (pinneo como PiRpcBackend: `--continue` agrupa sesiones por cwd y sin pinneo la memoria puede romperse entre reinicios); `--` antes de la orden posicional (órdenes que empiecen por «-»); exit != 0 con stdout con texto → se lee el texto (stop length: es la respuesta que alcanzó a dar), exit != 0 sin texto → voz de error.

## Objetivo

«Nyx, ¿qué branch tengo?» con el servicio recién arrancado y cero procesos pi: arranca pi, responde en voz alta, muere. La orden siguiente recuerda la anterior.

## Objetivos

1. Nuevo valor de `[orders] backend`: `"efimero"`. Los backends existentes (herdr/pi/auto) quedan intactos.
2. `send(orden)`: si hay un pi trabajando → `(False, "ocupada…")`; si no → lanza pi one-shot con la orden y devuelve `(True, "")` inmediatamente (no bloquea el hilo de voz).
3. Al terminar el one-shot: la respuesta se lee en voz alta por el servicio (`say(brief=True)`), igual que hace voice.ts hoy; pi muere. Si pi falla (exit != 0, sin salida): voz de error clara.
4. Memoria: `--session-dir` (el mismo `STATE_DIR/<agente>-sessions` que usa el backend pi) + `--continue`. Nada de contexto perdido entre órdenes.
5. Estado visible: el tray/status muestra working mientras el one-shot vive, idle en reposo. «En reposo» NO es "no disponible": no hay nada que arrancar.

## No-objetivos

- Cola de órdenes (rechazo, decidido).
- Idle timeout / proceso residente (rechazado).
- Notificaciones de escritorio (solo voz, decidido).
- Cambiar los backends existentes ni el default de `auto`.
- Comando de voz para resetear la sesión (open question).

## Decisiones de implementación

**D1 — `EfimeroBackend`** (nyx/orders.py): hermano de `PiRpcBackend`. `status()` → `"working"` si el subprocess vive, `"idle"` si no (NUNCA None: en reposo está "disponible", no rota). `send(order)` → busy-check → `Popen(["pi", "-p", "--", order, "--session-dir", …, "--continue", *pi_args_for(cfg, with_herdr=False, voice=False)], cwd=Path.home())` SIN voice.ts (la voz la pone el propio backend: doble lectura si no) → hilo lector espera `communicate()`, y con el texto final llama `self.on_say(texto, brief=True)`; exit != 0 con stdout vacío → `on_say` con error de una frase; exit != 0 con texto → se lee el texto. `stop()` → mata el subprocess si vive. `launch()` → `(True, "…lista; las órdenes la arrancan. Dile: «Nyx, …»")` (nada que lanzar; ese mismo texto sirve para `nyx agent`).

**D2 — Cableado de la voz**: `Orchestrator`/backend recibe un callback `on_say` (app pasa su `say` existente). `PiRpcBackend` y `HerdrBackend` lo ignoran (su voz es voice.ts); `EfimeroBackend` lo usa. Inyección por parámetro del constructor o atributo — a criterio del builder sin romper los tests existentes.

**D3 — choose_backend y registro**: acepta `"efimero"` → `("efimero", "")` sin tocar herdr/pi. Además: `name = "efimero"` en la clase y entrada en el dict de `Orchestrator._pick` (sin ella, el backend sería None para siempre). El supervisor (`start_supervisor`): con efimero, `status()` nunca es None → no intenta lanzar nada (el loop existente ya no-op-ea con este contrato; verificar en test — patchear `time.sleep` para cortar el ciclo o extraer el tick, a criterio del builder).

**D4 — timeout del one-shot**: sin límite duro por defecto (una orden puede durar minutos con herramientas); si el proceso pi queda zombi (imposible terminar), `stop()` al reiniciar el servicio lo mata. Riesgo aceptado y documentado.

**D5 — `nyx agent` (CLI)**: usa el mismo texto de `launch()` ("el agente efímero no tiene proceso residente: dile «Nyx, …» y arranca solo" como idea; unificado con D1) y sale 0.

**D5b — doctor**: `_doctor_orders` (nyx/doctor.py) gana rama efimero (~3 líneas): `r.ok("pi efímero", "arranca con cada orden; memoria en el fichero de sesión")` — sin "en marcha" residente (status idle/working como siempre).

**D6 — config/docs**: comentario de `backend` en `nyx/config.py` y sección `[orders]` nueva en `config.example.toml` (hoy no existe) con `backend = "efimero"` comentado; README (fila del backend y nota de que la memoria vive en el fichero de sesión). Docstring del módulo orders.py al día.

## Restricciones

- Solo `nyx/orders.py`, `nyx/app.py` (paso del callback say), `nyx/doctor.py` (rama efimero, D5b), `nyx/config.py`, `config.example.toml`, `README.md` y tests.
- Suite verde (Linux + Windows) y ruff; sin dependencias nuevas.
- Tests del backend SIEMPRE con `pi` falso (script ejecutable o Popen fakeado, patrón `FAKE_PI` existente) — nunca un pi real en CI.

## Criterios de aceptación (Given/When/Then)

- **A1** G: servicio recién arrancado, `backend="efimero"`, cero procesos pi. W: orden de voz. T: se lanza UN pi one-shot con `--continue` y la sesión compartida; la respuesta llega a `on_say` con `brief=True`.
- **A2** G: one-shot en marcha. W: orden nueva. T: `(False, "ocupada…")` y NO se lanza otro pi.
- **A3** G: one-shot que termina con exit != 0 (fake). W: lectura del resultado. T: `on_say` recibe mensaje de error de una frase, no crash, el estado vuelve a idle.
- **A4** G: dos órdenes seguidas (fake pi que loggea sus args). T: la segunda se lanza con `--continue`, el MISMO `--session-dir` y el mismo `cwd` que la primera.
- **A5** G: supervisor corriendo, backend efimero. W: un ciclo completo sin órdenes. T: cero lanzamientos (status nunca None).
- **A6** G: `status()` con subprocess vivo/muerto. T: working/idle respectivamente; nunca None.
- **A7** G: `choose_backend` con `"efimero"`. T: `("efimero", "")`; con auto/herdr/pi, comportamiento de hoy intacto.
- **A8** (unit) G: `stop()` con one-shot vivo. T: se termina el proceso.

## Casos límite

- Respuesta vacía de pi (stdout vacío, exit 0): tratada como error con aviso (A3 cubre el espíritu).
- Stop length (exit != 0 con texto parcial): se lee el texto (decisión del orquestador).
- Tray muestra "(segundo plano)" con efimero: cosmético impreciso, aceptado (fuera de alcance).
- Salida con Markdown (tablas, código): `say(brief=True)` ya limpia/recorta (camino existente).
- Reinicio del servicio con one-shot vivo: systemd mata el grupo; `stop()` defensivo igual.
- Sesión corrupta: pi `--continue` decide; si pi falla, A3 lo comunica.
- Orden a mitad de la muerte del servicio: sin persistencia extra que cuidar.

## Qué queda a criterio del builder

- Cómo capturar la respuesta de `pi -p` (stdout completo; stderr al log del agente como hace PiRpcBackend).
- Estructura exacta del hilo lector y del busy-check (lock existente del backend pi como referencia).
- Mensajes exactos de voz, tono del repo.

## Preguntas abiertas

- ¿Comando de voz para "sesión nueva" (olvidar todo)? Default v1: no; borrar el fichero de sesión a mano (`nyx agent reset` futuro).
