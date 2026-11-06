# Plan de implementación: 002 — Trinity del día a día

> Ejecutar con la skill `executing-plans`, tarea a tarea. Pasos con checkbox `- [ ]`.

**Objetivo:** `jerga vol` y `jerga remind` (CLI, patrón launch) + secciones de skill «Volumen y recordatorios», «GitHub» y «Rituales».
**Arquitectura:** dos módulos nuevos despachados en `app.py` antes de `prepare()`; timers de systemd que disparan notify-send + `jerga say`; el resto es texto de skill. Cero dependencias nuevas.
**Stack:** Python estándar (`subprocess`, `datetime`, `json`, `re`), pytest con binarios SIEMPRE mockeados, `pactl`/`systemctl`/`gh` solo en producción.
**Spec:** `docs/specs/002-trinity-del-dia-a-dia/spec.md` (D1–D5, A1–A8).

## Restricciones globales

- Rama `feat/002-trinity-dia-a-dia` desde main. Sin merge ni push (orquestador tras review).
- Verde en cada commit: `uv run pytest -q tests` + `uv run ruff check .`. CI Linux+Windows.
- LECCIONES DEL 001 (obligatorias): fixture autouse de `sys.platform = "linux"` en los tests nuevos; `shutil.which`/`subprocess` mockeados — nada de binarios reales; stub win32 en ambos subcomandos.
- Nada de arrancar apps ni reproducir nada en la máquina del usuario durante la verificación.

## Foco de revisión

1. **Ejecución real de pactl/systemctl en tests** → todos los tests construyen comandos o mockean (001 S2).
2. **Plataforma win32 rompiendo tests de contrato** → fixture + stubs (001 S1).
3. **HH:MM que ya pasó hoy → mañana** (A3) → test de `parse_when` con `now` inyectado.
4. **Unidades pisándose** (dos recordatorios, mismo nombre) → contador desde `list-timers`, test.
5. **Recordatorio con volumen a 0 perdido sin rastro** → el comando disparado incluye notify-send (A3), test de construcción.

### Tarea 1: `jerga vol` + línea de skill

**Ficheros:** Crear `jerga/vol.py`, `tests/test_vol.py`; Modificar `jerga/app.py` (dispatch + docstring), `jerga/trinity/SKILL.md` (sección «Volumen y recordatorios»: parte volumen).

**Interfaces:**

```python
def build_cmd(orden: str) -> list[str]          # → ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"] · "mute" → set-sink-mute + "toggle"
def read_volume() -> str | None                 # parsea `pactl get-sink-volume @DEFAULT_SINK@` → "30%"
def main(argv: list[str]) -> int                # argv: [] → up · ["down"|"mute"|"45"] · exit 0/EXIT_ERROR
```

- [x] Test primero (rojo): `build_cmd` para up/down/mute/N (default up, N con clamp 0–100 y aviso, no error); `read_volume` parsea salida real de pactl (string fixture); `main` sin pactl (`which`→None) → EXIT_ERROR + mensaje; stub win32; contrato de salida una línea («volumen al 30 %», «muteado»).
- [x] Implementar `vol.py` + dispatch en `app.py` antes de `prepare()` (junto a `launch`) + docstring.
- [x] Skill: sección «Volumen y recordatorios» con la parte de volumen («baja el volumen» → `jerga vol down` sin confirmación; también «ponlo al 30», «mútelo»).
- [x] `uv run pytest -q tests && uv run ruff check .` verdes.
- [x] Commit `jerga vol: volumen del sink por defecto por voz (pactl, ±10/mute/N)`.

### Tarea 2: `jerga remind` + skill

**Ficheros:** Crear `jerga/remind.py`, `tests/test_remind.py`; Modificar `jerga/app.py` (dispatch + docstring), `jerga/trinity/SKILL.md` (parte recordatorios).

**Interfaces (consume `EXIT_ERROR` estilo launch; produce):**

```python
def parse_when(texto: str, now: datetime | None = None) -> tuple[str, str]
    # ("--on-active=1200", "en 20 minutos") · ("--on-calendar=2026-11-07 18:00:00", "mañana a las 18:00")
    # acepta: Ns/Nm/Nh (con o sin espacio: "20m", "20 m", "20 minutos") · "HH:MM" (pasado → mañana)
def next_unit() -> str                           # "jerga-remind-7": max existing +1 (systemctl list-timers --output=json por `systemctl show` units jerga-remind-*)
def fired_cmd(texto: str) -> list[str]           # ["sh", "-c", "notify-send -t 60000 Recordatorio '<texto>'; jerga say 'Recordatorio: <texto>'"]
def main(argv: list[str]) -> int                 # ["apagar el fuego", "en", "20m"] · ["--list"] · ["--cancel", "7"]
```

- [x] Test primero (rojo): `parse_when` (20m→1200 s; 1h; "18:00" hoy futuro vs pasado→mañana; "90 s"; basura → ValueError); `fired_cmd` contiene notify-send + jerga say; contador de unidades con `list-timers` mockeado (dos existentes → siguiente); `--list`/`--cancel` construyen los systemctl correctos; servicio parado (`is_running`→False) → línea de aviso; >1 h vista → línea «si apagas el equipo, se pierde»; stub win32; escaping de comillas en el texto.
- [x] Implementar `remind.py` (`systemd-run --user … sh -c '…'` con lista de args, sin shell=True en la llamada) + dispatch + docstring.
- [x] Skill: parte recordatorios («avísame en 20 minutos de X» → `jerga remind "X" en 20m` sin confirmación; «¿qué recordatorios tengo?» → `--list`; «cancela el de las 18:00» → `--cancel`).
- [x] Suite + lint verdes. Verificación NO invasiva permitida: `jerga remind --list` real (solo lectura) muestra «sin recordatorios».
- [x] Commit `jerga remind: recordatorios one-shot con timers de systemd (notify-send + jerga say)`.

### Tarea 3: skill de GitHub y rituales

**Ficheros:** Modificar `jerga/trinity/SKILL.md` (secciones «GitHub» y «Rituales»); `README.md` (filas de `vol` y `remind` en la tabla de uso).

**Interfaces:** consume `jerga vol`/`jerga remind` ya en el venv (reinstalar como en 001-T3 con `uv pip install --python ~/.local/share/jerga/venv/bin/python --reinstall-package jerga "jerga @ file:///home/kx/dev/jerga"`).

- [x] Sección «GitHub» según D4: leer libre (`gh pr list -R`, `gh pr checks`, `gh pr view --comments`; sin repo: `gh search prs --author=@me --state=open`); actuar = cambio con «¿lo hago?» y texto exacto; nunca push --force; sin login → decirlo.
- [x] Sección «Rituales» según D5: «buenos días» (bloqueado primero → PRs → recordatorios → pieza del mundo) y «cierro el día» (a medias → mañana → nota en `~/Documentos/jerga/notas/cierre-<fecha>.md`). Sin formularios, 2-3 frases habladas.
- [x] Reinstalar en el venv + `jerga trinity restart` + confirmar idle con `herdr agent list`. SIN lanzar nada.
- [x] Suite + lint verdes.
- [x] Commit `Trinity: GitHub por voz (leer libre, actuar con confirmación) y rituales de arranque y cierre del día`.

## Auto-revisión

- Cobertura: D1 (T1), D2/D3-recordatorios (T2), D4 (T3), D5 (T3), A1/A2 (T1 tests), A3/A4/A5 (T2 tests), A6 (T1+T2 skill), A7/A8 (T3 skill).
- Foco de revisión: cada línea con su test (1→tests mock, 2→fixture/stub, 3→parse con now inyectado, 4→contador mock, 5→fired_cmd).
- Consistencia: ambos módulos replican el patrón launch (EXIT_*, stub win32 en main, stdout para Trinity).
