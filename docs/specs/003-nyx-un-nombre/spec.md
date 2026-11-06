# 003 — Nyx: un nombre para el programa y la agente (renombrado de jerga/Trinity)

## Contexto

El producto se llama hoy `jerga` y su agente por voz `Trinity`. Dos nombres para una sola experiencia genera confusión («¿le hablo a jerga o a Trinity?»). Decisión del humano: **un único nombre — Nyx** (diosa primigenia de la noche) para agente Y programa, con el **cuervo como símbolo** (oscuro, tranquilo, lo ve todo — ya es el carácter de la SKILL actual). La fonética es limpia para despertarla en español (*Nyx*, una sílaba) y para CLI: `nyx launch`, `nyx remind`.

`nyx` está ocupado en PyPI (`nyx-dictado` libre): publicar en PyPI NO es objetivo; si algún día se publica, será bajo otro id y no condiciona este renombrado.

## Objetivo

Decir «Nyx, buenos días» y ejecutar `nyx launch steam` siendo la misma entidad. Todo lo que hoy dice jerga/Trinity dice Nyx, y el usuario no pierde ni su config ni sus notas ni sus recordatorios en el camino.

## Objetivos

1. Renombrar el paquete Python (`jerga` → `nyx`), CLI, unidad systemd, rutas de config/estado/notas y agente (nombre, wake word, workspace, persona).
2. **Migración automática**: al primer arranque de `nyx`, las rutas antiguas (`~/.config/jerga`, `~/.local/state/jerga`, `~/Documentos/jerga`) se mueven a las nuevas con backup, no se duplican.
3. Alias de transición: `jerga` sigue funcionando (mismo binario, aviso de renombrado la primera vez) una o dos versiones.
4. Repo GitHub renombrado `kcurtet/jerga` → `kcurtet/nyx` con URLs de instalador actualizadas (los redirects de GitHub cubren las viejas).
5. Cuervo como símbolo: presente en README (texto/ASCII), en el docstring del CLI y como guiño en la persona de la SKILL — sin generar arte gráfico.

## No-objetivos

- Publicar en PyPI.
- Cambiar personalidad, protocolos ni comportamientos de la agente: es un renombrado, la persona es la misma.
- Rediseño de logo/branding gráfico.
- Renombrar `herdr`, `pi` ni nada ajeno al repo.
- Identidad de ventana GTK (application_id, clase CSS, namespace layer-shell `jerga`): se conserva a propósito — cambiarlos puede romper reglas de ventana del compositor del usuario; se renombrará cuando toque revisar la UI. (Decisión registrada en la review del 003.)

## Anti-objetivos

- No dejar rutas antiguas vivas por siempre: migración una vez, backup, y a correr.
- No romper la suite ni la CI: mismo verde que hoy (135+) tras el rename en Linux y Windows.

## Decisiones de implementación

**D1 — Paquete y CLI.** Directorio `jerga/` → `nyx/`; `pyproject.toml` name `nyx`, binario `nyx`; `python -m nyx`; todos los imports internos y tests actualizados. La unidad systemd pasa a `nyx.service` (el instalador crea la nueva y la vieja `jerga.service` se desactiva si existe). Docstring/README con el cuervo.

**D2 — Rutas y migración.** Constantes: config `~/.config/nyx/`, estado `~/.local/state/nyx/`, notas `~/Documentos/nyx/`. En el arranque, si existe la ruta vieja y la nueva no: mover (renombrar) la vieja y dejar un backup comprimido o copia `.pre-nyx/` — decisión menor del builder, pero el resultado debe ser: datos intactos, una sola copia viva, huella de lo anterior. La migración se loguea y se cuenta en `nyx doctor`.

**D3 — Alias `jerga`.** El instalador crea además un symlink/bin `jerga` que ejecuta `nyx` (mismo punto de entrada). Primera ejecución por el alias: una línea por stderr avisando del nuevo nombre (no en cada uso). A desaparecer en una versión futura (nota en README).

**D4 — La agente.** `orders.py`: `agent = "nyx"`, `wake_words = ["nyx"]` (el matching ya es plegado; «Nyx» despierta). Directorio `trinity/` → `nyx/` con la SKILL renombrada: «Eres Nyx» + el guiño del cuervo donde hoy hay referencias al navegador/visión («el cuervo que lo ve todo» en `look`); el resto del texto queda igual. `jerga trinity` (subcomando) pasa a `nyx nyx`? No: subcomando renombrado a `nyx agent` — decisión: el subcomando de gestión se llama `agent` (ej. `nyx agent restart`), y `trinity` se acepta como alias silencioso una versión. Workspace de herdr: la próxima vez que el supervisor la arranque se creará con etiqueta `nyx` (la vieja `trinity` se cierra sola como hoy hace con huérfanos).

**D5 — Instaladores y repo.** `install.sh`/`install.ps1` actualizados (URLs nuevas `kcurtet/nyx`, unidad, binario, alias). Renombrar el repo en GitHub tras mergear (los redirects cubren `raw.githubusercontent` y clones viejos). README reescrito en su cabecera (nombre, una línea de qué es, el cuervo ASCII pequeño) sin tocar el resto de contenido salvo s/jerga/nyx/.

**D6 — Máquina del humano.** Tras el merge: reinstalar en el venv/servicio real, migrar las rutas del usuario, reiniciar la agente (ya como Nyx, wake «Nyx»), y comprobar `nyx remind --list` y una orden de voz por el humano («Nyx, ¿qué recordatorios tengo?»).

## Restricciones

- Suite verde (Linux+Windows) y ruff en cada commit; mismo estilo de tests (binarios mockeados).
- La migración de rutas debe ser idempotente (segundo arranque no re-migra) y testeada con tmp_path.
- Nada de arrancar apps ni reproducir nada en la máquina del usuario durante la verificación.

## Criterios de aceptación (Given/When/Then)

- **A1** Given instalación limpia, when `nyx --version` / `nyx launch --list`, then funciona como hoy `jerga`.
- **A2** Given `~/.config/jerga` y `~/.local/state/jerga` existentes, when primer arranque de `nyx`, then se migran a las rutas nuevas con backup y el segundo arranque no toca nada.
- **A3** Given el alias, when `jerga remind --list`, then funciona y la primera vez avisa del renombrado por stderr.
- **A4** Given la SKILL nueva, when «Nyx, pon música», then despierta (wake «nyx») y responde como Nyx con el cuervo en la mirada; «Trinity» YA NO despierta (el alias de wake no existe: solo el nombre nuevo).
- **A5** Given el instalador nuevo, when se instala en la máquina real, then `nyx.service` activo, `jerga.service` fuera, agente en workspace `nyx` idle.
- **A6** Given la suite, when CI, then verde en ubuntu y windows.
- **A7** Given el repo renombrado, when curl a la URL vieja de install.sh, then redirect a la nueva y funciona.

## Casos límite

- Ruta vieja y nueva a la vez (usuario ya probó nyx antes de migrar): gana la nueva, la vieja se respeta y se avisa.
- `~/.config/jerga` existe pero vacío: migrar igual (barato) o ignorar — criterio del builder, documentado en el código.
- Usuario con `jerga.service` corriendo al instalar: parar/desactivar la vieja, arrancar `nyx.service`.
- Wake «nyx» dentro de una frase normal («el nexus…»): el matching por palabra completa ya lo protege; test de `_fold`/regex con «nexus» no despierta.
- Windows: rutas `%APPDATA%\jerga` → `\nyx` mismas reglas.

## Qué queda a criterio del builder

- Cómo estructurar la migración (función en `config.py`, arranque del servicio, o `nyx doctor --migrate`).
- Backup como copia dir vs zip.
- Orden mecánico del renombrado (un mega-commit por capas vs commits por área) — pero cada commit verde.

## Preguntas abiertas

- Ninguna bloqueante. El alias `jerga` se retira «en una versión futura»: se anota en README, sin fecha.
