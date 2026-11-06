# Plan de implementación: 003 — Nyx, un nombre para el programa y la agente

> Ejecutar con la skill `executing-plans`, tarea a tarea. Pasos con checkbox `- [ ]`.

**Objetivo:** renombrar jerga→nyx (paquete, CLI, rutas, servicio, instaladores) y trinity→nyx (agente), con migración automática de las cosas del usuario y alias de transición.
**Arquitectura:** barrido mecánico en 4 commits verticales (paquete → rutas+migración → servicio/instaladores → agente) + puesta a punto de la máquina real. Cada commit verde. Las correcciones del builder-check ya viven en la spec (estado en `~/.local/state/nyx`, venv aparte, wake rewrite, timers recreados, sessions renombradas, workspace trinity cerrado en D6, NYX_* con fallback, skill mecánica).
**Stack:** Python estándar, pytest (rutas con tmp_path, binarios mockeados), install.sh/ps1, systemd user units.
**Spec:** `docs/specs/003-nyx-un-nombre/spec.md` (D1–D6, A1–A7, casos límite).

## Restricciones globales

- Rama `feat/003-nyx` desde main. Sin merge/push (orquestador tras review).
- Verde en cada commit: `uv run pytest -q tests` + `uv run ruff check .`.
- Nada de arrancar apps ni tocar las rutas REALES del usuario durante las tareas 1–4 (la migración se prueba con tmp_path); la tarea 5 sí toca la máquina, con pasos aprobados.
- LECCIÓN 002 (conftest): nada de fixtures que dependan de nombres de módulo de pytest.

### Tarea 1: paquete y CLI

**Ficheros:** `jerga/` → `nyx/` (git mv), `pyproject.toml`, todos los imports, `tests/`.
**Pasos:** rama · `git mv jerga nyx` + s/jerga/nyx/ en imports y refs (`python -m nyx`, entry point `nyx=nyx.app:main`) · docstring con el cuervo (una línea + ASCII pequeño de 3 líneas) · suite+ruff verde · commit `nyx: el paquete jerga pasa a llamarse nyx (barrido de imports y CLI)`.

### Tarea 2: rutas y migración de las cosas del usuario

**Ficheros:** `nyx/config.py` (STATE_DIR→`~/.local/state/nyx`, config→`~/.config/nyx`, notas→`~/Documentos/nyx`), nueva `nyx/migrate.py`, tests.
**Produce:** `migrate.run() -> list[str]` (msgs de lo migrado) — idempotente: por cada par (vieja, nueva): si existe vieja y no nueva → renombrar y dejar copia de seguridad `<vieja>.pre-nyx` solo de config.toml; dentro del estado renombra `trinity-sessions`→`nyx-sessions` y `trinity-pi.log`→`nyx-pi.log`; reescribe en config.toml valores conocidos: wake_words/agent "trinity"/"trini"→["nyx"], y cualquier "jerga" en claves de rutas. Se llama desde `main()` al arrancar (y desde `nyx doctor`, contando lo migrado). Windows espejo con `%APPDATA%`/`%LOCALAPPDATA%`.
**Tests:** migración completa con tmp_path (HOME/PYTHON overlay), idempotencia (2ª llamada no toca), vieja+nueva a la vez (gana nueva, avisa), config con wake_words trinity→nyx, sessions renombradas.
**Commit:** `nyx: rutas nuevas (~/.config/nyx, ~/.local/state/nyx) con migración automática idempotente`.

### Tarea 3: servicio, instaladores, alias y entorno

**Ficheros:** `install.sh`, `install.ps1`, `nyx/platform_env.py`/`hotkey.py`/`trinity/voice.ts`.
**Pasos:** unidad `nyx.service` (desactiva `jerga.service` si existe) · venv prefix `~/.local/share/nyx` + bin `nyx` + symlink alias `jerga` (aviso una sola vez: marker en STATE_DIR) · URLs `kcurtet/nyx` · `JERGA_*`→`NYX_*` con lectura-fallback de `JERGA_HOME` · socket `nyx.sock` · par uinput ATÓMICO: `UINPUT_NAME="nyx-virtual-keyboard"` + autofiltro `nyx` not in d.name (test que falla si se desincronizan) · subcomando `trinity` aceptado como alias silencioso de `agent`.
**Tests:** alias marker, fallback env, uinput par, unidad generada.
**Commit:** `nyx: servicio, instaladores y entorno (unidad nyx, alias jerga, NYX_*, socket)`.

### Tarea 4: la agente Nyx

**Ficheros:** `nyx/orders.py`, `nyx/trinity/` → `nyx/nyx/` (dir de la skill), SKILL.md, README.
**Pasos:** DEFAULTS `agent="nyx"`, `wake_words=["nyx"]` · skill renombrada: «Eres Nyx» + cuervo en la mirada, s/jerga→nyx/ mecánico en comandos y rutas, ejemplos «repo jerga»→«repo nyx» · subcomando principal `nyx agent` · README reescrito en cabecera (nombre, cuervo ASCII) manteniendo el resto.
**Tests:** wake "nyx" sí / "trinity" ya no / "nexus" no (palabra completa), pi_args_for sin jerga.
**Commit:** `nyx: la agente es Nyx (skill, wake y subcomando agent)`.

### Tarea 5: máquina real (orquestador + humano)

Instalar (`./install.sh`), verificar migración real (config/estado/notas movidos con backup), cerrar workspace `trinity` de herdr, `nyx agent restart`, `nyx remind --list` recreando timers viejos si los hay, y prueba de voz del humano: «Nyx, ¿qué recordatorios tengo?». Repo GitHub renombrado (kcurtet/nyx) y URLs de install verificadas con curl (A7).

## Foco de revisión

1. Migración que duplica en vez de mover (datos del usuario) → tests de idempotencia.
2. Wake: config del usuario con "trinity" sobrevive → rewrite testeado.
3. uinput/autofiltro desincronizados (el servicio se escucha) → test del par.
4. Venv "migrado" (roto) → spec D2: el venv lo reinstala el installer, nunca se mueve.
5. SKILL enseñando comandos muertos → s/jerga→nyx/ mecánico completo.
