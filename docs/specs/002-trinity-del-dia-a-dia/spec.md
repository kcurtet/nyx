# 002 — Trinity del día a día: volumen, recordatorios, GitHub y rituales

## Contexto

Trinity ya orquesta agentes, abre apps, lee notas y busca en la web. Pero las cosas que una dice diez veces al día — «baja el volumen», «avísame en 20 minutos», «¿tengo PRs?» — todavía no las tiene. Esta spec agrupa cuatro capacidades pequeñas con el mismo espíritu: la orden explícita es el permiso, lo delicado se confirma.

Hechos verificados en la máquina: `pactl` ✓, `gh` ✓, systemd `--user` ✓ (jerga ya corre como servicio con `jerga say` para hablar), no hay `at`/`playerctl`.

## Objetivo

Cuatro capacidades por voz, sin configuración nueva ni dependencias:

1. **Volumen**: «baja el volumen», «mútelo», «ponlo al 30 %».
2. **Recordatorios**: «avísame en 20 minutos de apagar el fuego» → TTS a la hora.
3. **GitHub**: «¿tengo pull requests abiertos?», «¿ha pasado el CI de jerga?», «léeme los comentarios del PR X».
4. **Rituales**: «buenos días» y «cierro el día» como recetas fijas de repaso.

## Objetivos

- Volumen y recordatorios como subcomandos CLI de jerga (`jerga vol`, `jerga remind`), patrón `launch`: testeables y usables a mano.
- GitHub y rituales como secciones de la skill de Trinity usando `gh` y lo que ya tiene (sin código nuevo).
- Recordatorios persistentes sin demonio nuevo: timers de systemd que disparan `jerga say` a través del servicio.

## No-objetivos

- Recordatorios recurrentes («cada día a las 9»): one-shot solo; recurring queda como pregunta abierta.
- Control de mpd/reproductores: ya cubierto aparte (sección «Música y media» de la skill, tras instalar mpd/mpc/playerctl).
- Brillo/pantallas (falta `brightnessctl`).
- Acciones de GitHub sin confirmación (comentar, mergear): siempre con «¿lo hago?» y el texto exacto visible.
- Cambiar el volumen de apps concretas: el sink por defecto basta.

## Anti-objetivos

- No hablar de la mano del servicio: los timers viven en systemd, no en un hilo del proceso de jerga (sobreviven a reinicios del servicio).
- No silenciar el protocolo de confirmación para nada con efectos más allá de lo trivial.

## Decisiones de implementación

**D1 — `jerga vol [up|down|mute|N]`** (por defecto `up`): pasos de ±10 % sobre el sink por defecto, `mute` conmuta, `N` fija el porcentaje (0–100). Ejecuta `pactl set-sink-volume @DEFAULT_SINK@ …` (y `set-sink-mute` para mute). Sin confirmación de Trinity: es trivial y reversible. Salida: una línea («volumen al 30 %», «muteado») que Trinity lee; exit ≠ 0 con mensaje si `pactl` falta o PulseAudio/PipeWire no responde.

**D2 — `jerga remind "texto" en <cuándo>`**: one-shot. `<cuándo>` acepta «Nm»/«Nh»/«N s» y «HH:MM» (24 h, hoy o mañana si ya pasó). Crea `systemd-run --user --on-active=<segundos>|--on-calendar=<fecha> --unit=jerga-remind-<n> --description=… sh -c 'notify-send -t 60000 "Recordatorio" "<texto>"; jerga say "Recordatorio: <texto>"'` — TTS con respaldo visual: un aviso con el volumen en 0 (o sin auriculares) no se pierde sin rastro. Las unidades son transitorias: **se pierden si cierras sesión o apagas la máquina**; al crear un recordatorio a más de una hora vista, la salida lo avisa («si apagas el equipo, se pierde»). La unidad se nombra con contador creciente (o marca de tiempo) para que varios recordatorios no se pisen. `jerga remind --list` muestra los timers vivos con su texto (via `systemctl --user list-timers jerga-remind-* --all` + description) y `jerga remind --cancel <n>` los cancela. Si el servicio de jerga no está corriendo, el timer dispara igual pero no suena: al crear el recordatorio, avisar en la salida («Trinity no sonará si jerga está parado» solo si `is_running()` es falso). Windows: stub honesto como `launch` (D6 del 001).

**D3 — Skill: sección «Volumen y recordatorios»**: órdenes de volumen y aviso mapean directo a `jerga vol`/`jerga remind` sin confirmación (pedido explícito, trivial/reversible); «¿qué recordatorios tengo?» → `jerga remind --list`; «cancela el de las 18:00» → `--cancel`.

**D4 — Skill: sección «GitHub»**: leer es libre. Con repo nombrado: `gh pr list -R <repo>` (resuelve el repo en `~/dev` como siempre), `gh pr checks`, `gh pr view --comments`. Sin repo en contexto, «¿tengo pull requests?» = PRs **autoría mía** abiertos donde sea: `gh search prs --author=@me --state=open` (una llamada, rápido para voz; los ~45 repos de `~/dev` uno a uno sería lento). Resumen hablado de una o dos frases, detalle en el panel. Actuar (comentar, mergear, cerrar) es cambio: anunciar exactamente qué (repo, PR, texto) y esperar el sí; nunca push --force.

**D5 — Skill: sección «Rituales»**: dos recetas:
- **«buenos días»**: estado de los orquestadores (lo bloqueado primero), PRs abiertos (`gh`), recordatorios del día (`jerga remind --list`), y una pieza del mundo a elección (web). Dos o tres frases.
- **«cierro el día»**: qué quedó a medias (orquestadores trabajando/bloqueados), recordatorios pendientes mañana, y pregunta si quiere dejar una nota; si dice que sí, se dicta y va a `~/Documentos/jerga/notas/cierre-<fecha>.md` (convención de notas existente). Dos frases.
No son formularios ni comandos nuevos: recetas de secuencia con lo que ya tiene.

## Restricciones

- Python estándar + lo que ya usa jerga; cero dependencias nuevas.
- Suite actual (pytest Linux+Windows) verde; los tests de systemd/pactl/gh se abstraen con monkeypatch (lección del 001: nada de binarios reales en tests).
- CI Windows: `vol` y `remind` llevan stub win32 como `launch`.

## Criterios de aceptación (Given/When/Then)

- **A1** Given PipeWire con sink por defecto, when `jerga vol down`, then `pactl set-sink-volume @DEFAULT_SINK@ -10%` se ejecuta y la salida es una línea legible (test unitario del comando construido, no del sonido).
- **A2** Given `pactl` ausente, then exit ≠ 0 y mensaje claro.
- **A3** Given «en 20m», then timer `--on-active=1200` con unidad `jerga-remind-*` que ejecuta notify-send + `jerga say`; given «a las 18:00» y son las 19:00, then `--on-calendar` de mañana.
- **A4** Given dos recordatorios, then unidades distintas; `--list` muestra ambos con su texto; `--cancel <n>` deja uno.
- **A5** Given servicio parado, when se crea recordatorio, then la salida avisa de que no sonará.
- **A6** Given la skill, when «baja el volumen», then `jerga vol down` sin confirmación; when «avísame en 10 minutos de X», then `jerga remind "X" en 10m` sin confirmación.
- **A7** Given la skill, when «¿tengo pull requests?», then Trinity lee con `gh pr list` y resume SIN confirmación; when «comenta en el PR 12 "buen trabajo"», then anuncia repo+PR+texto y espera el sí.
- **A8** Given la skill, when «buenos días», then Trinity ejecuta la receta D5 y responde en 2-3 frases sin formularios.

## Casos límite

- «HH:MM» justo ahora / hace un minuto → mañana.
- Porcentaje fuera de 0–100 → clamp con aviso, no error.
- `jerga remind` sin `systemd-run` (¿no Linux?) → mensaje claro (win32 cubierto por stub).
- Texto del recordatorio con comillas → escapado al construir el comando.
- `--list` con cero timers → «sin recordatorios», exit 0.
- `gh` sin login → Trinity lo dice y sugiere `gh auth login` (no lo ejecuta).

## Qué queda a criterio del builder

- Parsing exacto de «en <cuándo>» (sufijos admitidos, espacios).
- Contador vs timestamp para nombrar unidades systemd.
- Redacción de las secciones de la skill, manteniendo el estilo seco actual.

## Preguntas abiertas

- Recordatorios recurrentes: si se quieren, otra iteración (`--on-calendar` repetido + limpieza).
