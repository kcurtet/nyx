# 005 — herdr sin terminal abierta

## Contexto

Tras el login, sin ninguna terminal abierta, Nyx no puede usar el backend herdr: en Linux el servidor de herdr solo existe cuando alguien lanza `herdr` en una terminal (no hay autostart), y todos los CLI que Nyx usa (`herdr agent …`, `herdr workspace …`) devuelven `server_not_running`.

Encima, el chequeo actual miente en dos sitios (verificado con herdr 0.9.3):

- `herdr status` **sale con código 0 aunque el servidor esté parado** (imprime `server: not running`); `herdr_available()` solo mira el código de salida, así que con `backend=auto` Nyx elige herdr igualmente y falla después con mensajes confusos.
- Algunos comandos (p.ej. `agent list`) devuelven **rc 0 con un cuerpo JSON de error** `{"error":{"code":"server_not_running",…}}`.

Y la solución existe: `herdr server` (sin subcomando) arranca el servidor **headless, sin TTY** («herdr server running; you can use any herdr CLI command in another terminal»), y el servidor sobrevive a la muerte de su cliente (ignora SIGHUP; verificado). Cuando el usuario abra una terminal y ejecute `herdr`, se attacha y ve los paneles de Nyx.

Decisión del humano (sesión 2026-11-08): arrancar el servidor **bajo demanda** desde Nyx (sin servicio systemd), con fallback solo en `auto`; flujo SDD completo.

## Objetivo

Orden por voz a Nyx justo después del login, sin abrir ninguna terminal, usando el backend herdr con sus paneles.

## Objetivos

1. Chequeo real de disponibilidad: `herdr status --json` → `server.running == true` (con fallback a parsear el texto `status: running` si `--json` no existe).
2. Arranque bajo demanda: si herdr está instalado y el servidor caído, Nyx lanza `herdr server` detached y espera (timeout acotado) a que responda running.
3. Semántica de backend elegida por el humano:
   - `backend = "herdr"`: arranca el servidor; si no lo consigue, **error claro por voz, sin caer a pi** (reintenta en el próximo ciclo del supervisor).
   - `backend = "auto"`: herdr instalado → arranca el servidor y usa herdr; si no arranca o no está instalado → pi en segundo plano, como hoy.
4. Mismo camino para todas las entradas: servicio systemd, `nyx agent` (CLI) y `nyx doctor` comparten `choose_backend`, así que los tres obtienen el arranque bajo demanda.

## No-objetivos

- Servicio systemd / autostart de sesión para `herdr server` (evaluable luego; no ahora).
- Gestionar sesiones nombradas de herdr (`--session`): Nyx usa la default.
- Parar el servidor al cerrar Nyx: una vez arrancado, es del usuario (igual que su workspace). Desinstalar Nyx tampoco lo toca.
- Rotación del log del servidor.

## Decisiones de implementación

**D1 — Chequeo**: `herdr_available()` deja de fiarse del rc: ejecuta `herdr status --json` y exige `data["server"]["running"] is True` (estructura real verificada en 0.9.3: `{"client":{…},"server":{"status":"running","running":true,…}}`; parseo tolerante a claves ausentes). Si el JSON no parsea (herdr antiguo, rc 0), fallback textual buscando `status: running` bajo la sección server. rc != 0 o excepción → False. Hueco conocido y asumido: un herdr antiguo que rechace `--json` con rc != 0 da False aunque el servidor corra (auto cae a pi) — decisión consciente, no se persigue.

**D2 — Arranque bajo demanda** (`_ensure_herdr_server()` o nombre equivalente): si `which(herdr)` y no running → `Popen([exe, "server"], start_new_session=True, env=clean_child_env(), stdout=err=append a STATE_DIR/"herdr-server.log")`. Espera con **deadline wall-clock de ~8 s**: cada sondeo es `_herdr("status", "--json", timeout=2)` cada ~0.25 s, y se corta al deadline aunque un sondeo individual cuelgue (un herdr colgado no puede estirar el ensure a minutos). Devuelve (ok, motivo). Tolerante a carreras: si `herdr server` muere con "already running", re-chequear y aceptar si ya running. Nunca lanza dos servidores cuando ya hay uno. Detach POSIX con `start_new_session=True`; en Windows no se usan flags especiales — si `herdr server` no existe o falla allí, es el caso roto del que se cae a pi.

**D3 — Integración en `choose_backend`**: el check de pi va PRIMERO (como hoy): sin pi → `(None, motivo)` sin tocar herdr (HerdrBackend ejecuta pi como agente; arrancar un servidor sin pi es inútil). Luego, con `want="herdr"`: ensure; fallo → `(None, "…no he podido arrancar herdr…")`. Con `want="auto"`: herdr instalado → ensure; ok → `("herdr","")`, fallo → `("pi","")` (sin sermón: pi ya funciona igual). El supervisor existente (re-pick cada 20s) ya reintenta de serie: `choose_backend` NO memoice fallos del ensure. Coste declarado: `choose_backend` puede bloquear hasta ~10 s cuando ensure corre; sus llamadores actuales lo asumen (hilo del supervisor, arranque del servicio en app.py, `nyx agent` CLI, doctor — que además la llama dos veces: choose_backend + Orchestrator). El hilo de voz nunca llama ensure síncronamente: `send` → `launch` ya va a hilo daemon.

**D3b — Tests sin efectos**: en la suite, ensure/Popen/`_herdr` van simulados (fakes al estilo `FAKE_PI`); ningún test debe lanzar un `herdr server` real. `herdr_available()` conserva rol de pre-check barato dentro de ensure (check → spawn → wait).

**D4 — Normalizar errores de la CLI**: `_herdr()` trata un cuerpo JSON con `"error"` como fallo (rc efectivo 1); `data` SE CONSERVA (dict con el error) — útil para diagnóstico y para app.py, que no mira rc. Verificado con el revisor: hoy rc 0 + `{"error":…}` produce bugs reales (`HerdrBackend.status()` devolvía `"unknown"` en vez de None → `launch()` cree que ya está en marcha; `send()` éxito silencioso); con D4 todos los callers igual o mejor, ninguno roto. Los mensajes de voz existentes se quedan.

**D5 — `nyx doctor`**: al pasar por `choose_backend` puede arrancar el servidor como efecto colateral; si lo arranca, lo dice en su salida (`ok("herdr server arrancado por nyx", …)`), para que el diagnóstico no sorprenda.

**D6 — Log del servidor**: append simple en `STATE_DIR/herdr-server.log` (el estado actual ya usa `STATE_DIR` para logs de pi).

## Restricciones

- Solo `nyx/orders.py` (y `nyx/doctor.py` si D5 lo pide), tests, y documentación si procede (`config.example.toml`/README solo si cambia algo visible).
- Suite verde (Linux + Windows) y ruff; sin dependencias nuevas.
- Sin tocar el comportamiento con servidor ya corriendo.

## Criterios de aceptación (Given/When/Then)

- **A1** G: login fresco, servidor herdr caído, `backend=auto`, pi instalado. W: primera orden de voz. T: Nyx arranca `herdr server`, espera running, elige herdr y lanza al agente en su workspace (expectativa UX: primera orden ~1-2 s más; no es criterio de CI).
- **A2** G: `backend=herdr`, binario que arranca y muere (simulado en test). W: orden. T: mensaje de voz de fallo mencionando herdr, **sin** caer a pi; y choose_backend no memoice el fallo: un pick posterior vuelve a intentar el ensure.
- **A3** G: servidor ya corriendo. W: pick. T: cero procesos `herdr server` nuevos; backend herdr directo.
- **A4** G: `herdr status --json` responde `running:false` con rc 0. W: `herdr_available()`. T: False.
- **A5** G: CLI herdr devuelve rc 0 con JSON `{"error":…}`. W: `_herdr()`. T: se reporta como fallo (rc != 0 efectivo).
- **A6** G: servidor arrancado por Nyx; el servicio nyx se reinicia. W: nuevo pick. T: el servidor sigue vivo y se reutiliza (no se duplica, no se mata).
- **A7** G: `nyx agent` por CLI sin servidor. W: launch. T: arranca servidor y agente igual que el servicio.
- **A8** G: `herdr status --json` no soportado (stdout no-JSON, texto con `status: running`). W: `herdr_available()`. T: True por el fallback textual.

## Casos límite

- Carrera usuario/Nyx: el usuario abre terminal y arranca herdr mientras Nyx lanza `herdr server` → el de Nyx muere con "already running" → re-chequeo gana, sin duplicados.
- `herdr` instalado pero roto (exec falla, crash inmediato): ensure agota timeout → motivo en log y voz; auto cae a pi.
- Servidor cae a mitad de sesión (usuario lo para): el supervisor ya re-pick-ea; con esta spec, además lo rearranca.
- Windows: mismo camino; si `herdr server` no existe/falla allí, es el caso "roto" → auto cae a pi, `herdr` explícito da su error.

## Qué queda a criterio del builder

- Nombres concretos (`_ensure_herdr_server` vs similar), constantes de timeout/sondeo, y cómo estructurar el re-chequeo tras "already running".
- Cómo devolver "lo he arrancado yo" al doctor (retorno extra, atributo de módulo…), siempre que no ensucie la firma pública de `choose_backend`.
- Tests: fakes de `_herdr`/Popen siguiendo el estilo existente de `test_orders.py`.

## Preguntas abiertas

- ¿Avisar por voz la primera vez que Nyx arranca el servidor ("arranco herdr…")? Default actual: silencio (solo log); si molesta la latencia, se añade luego.
