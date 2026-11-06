# 001 — Lanzar apps y juegos por voz

## Contexto

jerga dicta; Trinity (la orquestadora por voz) ya puede mirar la pantalla, transcribir audios y manejar navegador y escritorio por accesibilidad (agent-browser/agent-desktop). Pero no puede **arrancar** nada: agent-desktop solo ve apps ya abiertas que expongan accesibilidad, y justo lo que la persona quiere lanzar (Steam, Project Zomboid) no la expone. Hoy «Trinity, ábreme Steam» acaba en un bash improvisado o en un «no puedo».

Hechos verificados en la máquina objetivo (CachyOS, KDE Wayland):

- Steam instalado en `~/.steam`; cada juego instalado tiene `steamapps/appmanifest_<appid>.acf` con `"name"` y `"appid"`.
- Atajos de juegos creados por Steam en `~/.local/share/applications/*.desktop` (p. ej. «Project Zomboid.desktop»); apps de sistema en `/usr/share/applications`.
- `gtk-launch`, `kioclient` y `steam` están en el PATH.
- El servicio de jerga (systemd --user, tras `graphical-session.target`) hereda entorno gráfico del session manager (`DISPLAY` y `WAYLAND_DISPLAY` están importados), igual que los paneles de herdr.

## Objetivo

Decir «Trinity, ábreme Steam» o «Trinity, lanza el Zomboid» y que la app arranque en la sesión gráfica, sin configuración previa, con respuesta hablada de una frase.

## Objetivos

1. Resolver nombres hablados — con errores de Whisper, sin tildes ni mayúsculas — a apps instaladas: entradas `.desktop` de usuario y sistema **y** juegos Steam instalados (appmanifests).
2. Lanzar la app de forma detached y fiable desde el contexto donde corra Trinity (servicio systemd o panel de herdr), sin arrastrar el `LD_PRELOAD`/`LD_LIBRARY_PATH` de CUDA de jerga.
3. Que Trinity lo use como vía directa (su skill), ejecutando sin confirmar cuando el pedido es explícito.

## No-objetivos

- Cerrar/matar apps o juegos por voz (trabajo sin guardar: otra iteración).
- Gestores tipo Lutris/Heroic/Bottles. Flatpak sale gratis si tiene `.desktop`.
- Alias manuales en `config.toml`: el matching plegado + el `vocabulary` de Whisper ya existente son la primera palanca si un nombre se destroza al dictar.
- Interfaz gráfica.

## Anti-objetivos

- No parsear `Exec=` para inyectarlo a mano cuando existe un lanzador estándar (`gtk-launch`): menos superficie de error con rutas, DBus activation y comillas.
- No buscar en internet ni instalar nada.

## Decisiones de implementación

**D1 — Pieza nueva: subcomando CLI `jerga launch <nombre>`.** Trinity ya habla con jerga por bash (`jerga look`, `jerga transcribe`); mismo patrón: testeable con pytest, y la persona también puede usarlo directamente. No es una tool de pi ni código dentro de la skill.

**D2 — Resolución en dos fuentes: entradas `.desktop` y appmanifests de Steam.** Fuentes `.desktop`: todos los `<dir>/applications` de `XDG_DATA_DIRS` (con los defaults estándar si la variable no está) — cubre usuario, sistema, `/usr/local/share` y exports de flatpak; el desktop-id derivado usa guiones para subdirectorios, como gtk-launch. Solo se lee la sección `[Desktop Entry]` (los nombres de Desktop Actions como «Store» o «Community» nunca son candidatas). Los atajos PWA del navegador («WhatsApp Web», «Instagram») son candidatos legítimos: los creó la persona a propósito. De los appmanifests se filtran los artefactos de Steam (Steam Linux Runtime, Proton, redistributables, voice files) por patrón de nombre; las bibliotecas se descubren vía `libraryfolders.vdf` (tolerante a su ausencia: solo la de por defecto). Matching plegado (minúsculas, sin tildes, como `_fold` de commands) por subcadena sobre `Name=` (incluidas `Name[es]`) y el nombre de fichero; `GenericName`/`Keywords` con menor peso; un match exacto gana siempre a los parciales. Entradas `NoDisplay=true`/`Hidden=true` fuera. Si un juego está en ambas fuentes, gana el `.desktop`, y es una sola candidata.

**D3 — Ejecución.** `.desktop` → `gtk-launch <desktop-id>` (id = nombre de fichero sin `.desktop`). Juego resuelto por appmanifest → `steam steam://rungameid/<appid>` (Steam se arranca solo si no está). Siempre detached: nueva sesión, stdio a `/dev/null`, entorno limpio de los LD de jerga; si faltara `DISPLAY`/`WAYLAND_DISPLAY`, se mergean desde `systemctl --user show-environment`.

**D4 — Contrato de salida (para Trinity y para los tests).** Éxito: exit 0 y una línea «OK <qué se ha lanzado>». Ambigüedad: exit ≠ 0 con las candidatas numeradas, una por línea; esos números son seleccionables: `jerga launch <misma consulta> --pick N` lanza la N-ésima, así Trinity cierra el bucle cuando la persona contesta «la segunda» (el orden de candidatas es determinista para que el índice re-resuelva igual). Nada encontrado: exit ≠ 0 con «no encuentro nada parecido a "X"» y hasta 3 sugerencias cercanas. Además `jerga launch --list [filtro]` lista los nombres disponibles (mirar es libre).

**D5 — Skill de Trinity: sección «Abrir apps y juegos».** Pedido explícito de abrir/lanzar algo → ejecutar `jerga launch` sin pedir confirmación (la orden ya es el permiso, como transcribir). Ambigüedad → UNA pregunta con las candidatas que devolvió el comando; si la persona contesta «la segunda», se re-lanza la misma consulta con `--pick 2`. Tras lanzar → confirmar en una frase. Cerrar apps sigue siendo acto delicado, fuera de esto.

**D6 — Windows: stub honesto.** El paquete es multiplataforma (CI en Windows): en win32 el subcomando existe pero responde que aún no sabe abrir apps ahí (exit ≠ 0), para que Trinity lo diga en vez de romper.

## Restricciones

- Python estándar + lo que jerga ya usa; cero dependencias nuevas.
- La suite actual (pytest Linux+Windows) debe seguir verde.

## Criterios de aceptación (Given/When/Then)

- **A1** Given el atajo «Project Zomboid.desktop», when `jerga launch "project zomboid"` (o `zomboid`), then exit 0 y gtk-launch recibe su desktop-id.
- **A2** Given un juego Steam **sin** atajo `.desktop` (en esta máquina: XCOM 2), when se pide por su nombre de appmanifest, then exit 0 y se lanza `steam steam://rungameid/<appid>` correcto.
- **A3** Given una consulta que matchea varias apps reales, then exit ≠ 0 y candidatas numeradas en stdout.
- **A4** Given una consulta sin matches, then exit ≠ 0, mensaje claro y hasta 3 sugerencias.
- **A5** Given un proceso sin `DISPLAY`/`WAYLAND_DISPLAY` en su entorno, then el lanzador los toma del session manager y el comando a ejecutar es el mismo (la inyección de env es unit-testeable).
- **A6** Given la skill actualizada, when «Trinity, ábreme Steam», then ejecuta `jerga launch steam` sin pedir confirmación; when pedido ambiguo, then pregunta una vez con las candidatas.
- **A7** Given appmanifests de runtimes/Proton en la carpeta de Steam, then no aparecen en `--list` ni como candidatas.
- **A8** Given una consulta ambigua y su lista numerada, when `jerga launch <consulta> --pick 2`, then se lanza exactamente la segunda candidata (orden determinista).

## Casos límite

- Nombres de `.desktop` con espacios («Project Zomboid.desktop»): desktop-id es el nombre de fichero completo sin extensión.
- ACF con formato KV de Valve (tabuladores, claves con mayúsculas/minúsculas variables): parseo tolerante.
- Steam no instalado: fuente ausente, sin error ni trace.
- Consulta vacía o de una letra: no matchea media biblioteca; mínimo de especificidad.
- Mismo juego en ambas fuentes: una sola candidata, no dos.
- Un mismo desktop-id en directorio de usuario y de sistema: gana el de usuario, no se lista dos veces.

## Qué queda a criterio del builder

- Estructura interna (módulo nuevo `launch.py` o donde encaje mejor).
- Scoring exacto y umbral de «varias candidatas» (≥2).
- Regex sencillo vs mini-parser KV para los ACF.
- Redacción exacta de mensajes, manteniendo D4.

## Preguntas abiertas

- Ninguna bloqueante. Si surgiera «que Steam actualice el juego antes de jugar»: `steam://rungameid` ya lo maneja Steam solo.
