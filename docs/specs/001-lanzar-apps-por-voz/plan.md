# Plan de implementación: 001 — Lanzar apps y juegos por voz

> Ejecutar con la skill `executing-plans`, tarea a tarea. Pasos con checkbox `- [ ]`.

**Objetivo:** `jerga launch <nombre>` resuelve apps instaladas (menú XDG + juegos Steam) y las arranca detached; Trinity lo usa por voz.
**Arquitectura:** módulo nuevo `jerga/launch.py` (escáner de fuentes + matching + ejecución) despachado desde `app.py` ANTES de `prepare()` (sin LD de CUDA). La skill de Trinity gana una sección que lo convierte en su vía directa. Cero dependencias nuevas, cero config nueva.
**Stack:** Python estándar (`pathlib`, `re`, `difflib`, `subprocess`, `dataclasses`), pytest, `_fold` existente de `jerga/commands.py`.
**Spec:** `docs/specs/001-lanzar-apps-por-voz/spec.md` (el plan argumenta desde ella: D1–D6, A1–A8).

## Restricciones globales

- Rama de trabajo: `feat/001-lanzar-apps` desde `main`. Sin merge ni push: los hace el orquestador tras review.
- Tests: `uv run pytest -q tests` y lint `uv run ruff check .` verdes en cada commit. CI corre pytest en Linux y Windows.
- Dispatch en `app.py` SIEMPRE antes de `prepare()` (como `look`): el proceso de lanzar no debe re-ejecutarse con `LD_PRELOAD`.
- Mensajes y candidatas por stdout (Trinity los lee); solo uso/ayudas por stderr.
- Español en nombres de tests y mensajes, estilo del repo (frases cortas, sin ruido).

## Foco de revisión

1. **Fuga de LD de CUDA al juego** (el servicio corre con `LD_PRELOAD`/`LD_LIBRARY_PATH` de jerga) → `launch_env` los quita: test en T2.
2. **Falta `DISPLAY`/`WAYLAND_DISPLAY`** (contexto servicio/sshd) → merge desde `systemctl --user show-environment`: test en T2.
3. **Desktop Actions («Store», «Community») colándose como candidatas** → `parse_desktop` solo lee `[Desktop Entry]`: test en T1.
4. **Orden no determinista rompe `--pick`** (segunda llamada resuelve distinto) → orden estable `(-score, nombre plegado, id)`: test en T2.
5. **Lluvia de ambigüedad con nombres genéricos** (PWAs «Workspace»…) → match exacto gana a subcadena: test en T2.

### Tarea 1: escáner de fuentes + `jerga launch --list`

**Ficheros:**
- Crear: `jerga/launch.py`
- Modificar: `jerga/app.py` (dispatch antes de `prepare()`; línea nueva en el docstring de uso)
- Test: `tests/test_launch.py`

**Interfaces (produce, y consume T2):**

```python
EXIT_OK, EXIT_AMBIGUOUS, EXIT_NOT_FOUND, EXIT_ERROR = 0, 3, 4, 5

@dataclass(frozen=True)
class Candidate:
    name: str                    # nombre mostrado: Name= o "name" del ACF
    folded: str                  # _fold(name), precalculado
    kind: str                    # "desktop" | "steam"
    desktop_id: str | None = None  # id para gtk-launch (subdirectorios → guiones)
    appid: str | None = None       # juego Steam
    path: str = ""                 # fichero de origen (debug)

def desktop_dirs() -> list[Path]        # XDG_DATA_HOME + XDG_DATA_DIRS (+defaults), sin duplicados
def parse_desktop(text: str) -> dict[str, str]   # SOLO [Desktop Entry], primera aparición de cada clave
def parse_kv(text: str) -> dict[str, str]        # pares "clave" "valor" de un appmanifest ACF
def steam_roots() -> list[Path]         # bibliotecas vía "path" de libraryfolders.vdf (ambas ubicaciones), fallback ~/.steam/steam
def collect() -> list[Candidate]        # .desktop de todos los dirs + juegos ACF; dedupe: desktop_id repetido gana el primero (usuario va antes), juego Steam cuyo nombre plegado ya está → fuera
def main(argv: list[str]) -> int        # por ahora: --list [filtro] · resto → EXIT_ERROR con uso
```

Constantes de filtrado: `NoDisplay`/`Hidden` con valor true (case-insensitive, sin comillas) fuera; artefactos Steam fuera por `re.compile(r"proton|steam linux runtime|redistributable|voice files", re.I)` sobre el nombre; ACF sin `appid` o sin `name` fuera.

- [ ] **Paso 1: tests del escáner (fallan)**

```python
# tests/test_launch.py
from pathlib import Path
import jerga.launch as L

DESKTOP = """[Desktop Entry]
Type=Application
Name=Project Zomboid
Name[es]=Project Zomboid
Exec=loquesea
"""

def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def test_parse_desktop_solo_desktop_entry():
    text = DESKTOP + "\n[Desktop Action Store]\nName=Store\n"
    d = L.parse_desktop(text)
    assert d["Name"] == "Project Zomboid"
    assert "Store" not in d.values()

def test_desktop_id_con_subdirectorio(tmp_path):
    _write(tmp_path / "sub" / "Kate.desktop", DESKTOP)
    # desktop_id derivado: sub-Kate
```

Y en el mismo fichero: fixtures con `monkeypatch.setattr(L, "desktop_dirs", lambda: [tmp])` y `monkeypatch.setattr(L, "steam_roots", lambda: [fake])` cubriendo: ACF real (appmanifest de Zomboid 108600 y un Proton filtrado), NoDisplay fuera, dedupe mismo desktop_id en dos dirs (gana el primero), juego ACF sin .desktop aparece, juego ACF con .desktop no se duplica, `main(["--list"])` imprime nombres (capsys) y `--list zomb` filtra plegado. Stub Windows: `monkeypatch.setattr(L.sys, "platform", "win32")` → `main([])` devuelve EXIT_ERROR y mensaje.

- [ ] **Paso 2: ejecutar y verificar que falla**
Run: `uv run pytest tests/test_launch.py -q`
Expected: FAIL — `No module named 'jerga.launch'` / AttributeError.

- [ ] **Paso 3: implementar `jerga/launch.py`** (solo lo de arriba: sin matching ni ejecución; `main` acepta `--list` y a todo lo demás responde uso + EXIT_ERROR; primera línea del módulo: stub win32 si `sys.platform == "win32"`)

Detalles fijados: glob recursivo `**/*.desktop`; desktop-id = ruta relativa al dir sin sufijo, `/` → `-`; Name visible = `Name` si existe, si no la primera `Name[xx]` alfabética; `steam_roots` lee `~/.steam/steam/config/libraryfolders.vdf` y `~/.steam/steam/steamapps/libraryfolders.vdf` (regex `"path"\s+"([^"]+)"`), dedup existentes, fallback raíz; appmanifests en `<root>/steamapps/appmanifest_*.acf`.

- [ ] **Paso 4: dispatch en `app.py`** antes de `prepare()` (junto a `look`):

```python
if cmd == "launch":
    from .launch import main as launch_main

    sys.exit(launch_main(args[1:]))
```

más una línea en el docstring: `jerga launch "nombre"  abre una app o juego instalado (--list para ver los nombres)`.

- [ ] **Paso 5: ejecutar y verificar**
Run: `uv run pytest -q tests && uv run ruff check .`
Expected: todo verde.
Run: `uv run python -m jerga launch --list zomb`
Expected: `Project Zomboid` (máquina real).

- [ ] **Paso 6: commit** `jerga launch: escáner de apps del menú XDG y juegos Steam (--list)`

### Tarea 2: matching, ejecución y contrato de salida

**Ficheros:**
- Modificar: `jerga/launch.py`
- Test: `tests/test_launch.py`

**Interfaces:**
- Consume: `Candidate`, `collect()`, constantes EXIT_* de T1.
- Produce:

```python
def match(query: str, cands: list[Candidate]) -> list[Candidate]  # ordenada, determinista
def launch_env(env: dict[str, str] | None = None) -> dict[str, str]
def launch(cand: Candidate, env: dict[str, str] | None = None) -> None
```

`main` crece: consulta → lanzar única / ambiguo / no encontrado / `--pick N`.

- [ ] **Paso 1: tests de matching (fallan)**

Cubrir con fixtures de T1: exacto gana («project zomboid» con un Zomboid y un «Project Zomboid Guide» → solo el exacto); subcadena («zomboid» → Zomboid); «total war» con dos juegos → 2 candidatas ordenadas por nombre plegado y MISMO orden en dos llamadas; consulta de <3 caracteres sin exacto → vacío; `GenericName`/`Keywords` matchean con menor rango (empate a subcadena: Name gana).

```python
def test_match_exacto_gana_a_subcadena():
    cands = [L.Candidate("Workspace", "workspace", "desktop", desktop_id="workspace"),
             L.Candidate("Notion Workspace", "notion workspace", "desktop", desktop_id="notion")]
    assert [c.name for c in L.match("workspace", cands)] == ["Workspace"]
```

- [ ] **Paso 2: ejecutar y verificar que falla**
Run: `uv run pytest tests/test_launch.py -q`
Expected: FAIL — no existe `L.match`.

- [ ] **Paso 3: implementar `match`** — orden: `(-score, folded, desktop_id or appid or "")`; score: exacto 100, subcadena en Name 50, en filename 40, en GenericName/Keywords 25; subcadena exige `len(fold(query)) >= 3`; exacto único → se devuelve solo él aunque haya parciales.

- [ ] **Paso 4: tests de env y ejecución (fallan)**

```python
def test_launch_env_quita_ld_y_merea_display(monkeypatch):
    fake = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-1"}
    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="DISPLAY=:0\nWAYLAND_DISPLAY=wayland-1\n"))
    env = L.launch_env({"LD_PRELOAD": "x", "LD_LIBRARY_PATH": "y", "PATH": "/usr/bin"})
    assert "LD_PRELOAD" not in env and "LD_LIBRARY_PATH" not in env
    assert env["DISPLAY"] == ":0" and env["WAYLAND_DISPLAY"] == "wayland-1"

def test_launch_usa_gtk_launch_o_steam(monkeypatch):
    calls = []
    monkeypatch.setattr(L.subprocess, "Popen", lambda *a, **k: (calls.append((a, k)), None)[-1])
    L.launch(L.Candidate("Project Zomboid", "project zomboid", "desktop", desktop_id="Project Zomboid"))
    L.launch(L.Candidate("XCOM 2", "xcom 2", "steam", appid="268500"))
    assert calls[0][0][0][:2] == ["gtk-launch", "Project Zomboid"]
    assert calls[1][0][0][:2] == ["steam", "steam://rungameid/268500"]
    assert all(k["start_new_session"] for _, k in calls)
```

Y de contrato (`main` con `collect` monkeypatcheado): única → imprime `OK Project Zomboid` y exit 0; ambigua → líneas `1) Nombre` + exit EXIT_AMBIGUOUS; nada → mensaje «no encuentro nada parecido a «X»» + hasta 3 sugerencias (`difflib.get_close_matches` sobre nombres plegados) + exit EXIT_NOT_FOUND; `--pick 2` sobre consulta ambigua lanza exactamente la segunda (Popen capturado) y el orden re-resuelve igual; binario ausente (`shutil.which` → None) → EXIT_ERROR; sin argumentos → uso por stderr + EXIT_ERROR.

- [ ] **Paso 5: ejecutar y verificar que falla** — igual que Paso 2, con los nuevos tests.
- [ ] **Paso 6: implementar `launch_env`, `launch` y el flujo completo de `main`**

`launch_env`: copia env (u `os.environ`), quita `LD_PRELOAD` y `LD_LIBRARY_PATH`; para cada clave de `("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY")` ausente, la busca en `systemctl --user show-environment` (subprocess con timeout corto; si falla, se ignora). `launch`: `gtk-launch <desktop_id>` o `steam steam://rungameid/<appid>`, `Popen(..., env=launch_env(env), start_new_session=True, stdin/stdout/stderr=DEVNULL)`; binario no en PATH → mensaje + EXIT_ERROR vía excepción propia capturada en `main`.

- [ ] **Paso 7: ejecutar y verificar**
Run: `uv run pytest -q tests && uv run ruff check .`
Expected: todo verde.

- [ ] **Paso 8: verificación real en la máquina — A CARGO DEL HUMANO** (regla del 2026-11-06: los agentes no lanzan nada en la máquina del usuario; XCOM 2 ya se probó OK antes del corte). Pendiente humano: `jerga launch steam` abre Steam, y `jerga launch "xcom"` a gusto. No bloquea el commit.

- [ ] **Paso 9: commit** `jerga launch: matching plegado, gtk-launch/steam detached y contrato de salida (--pick)`

### Tarea 3: skill de Trinity + integración de voz

**Ficheros:**
- Modificar: `jerga/trinity/SKILL.md` (sección nueva junto a «Navegador y escritorio»)
- Modificar: `README.md` (entrada en la lista de comandos, si existe tal lista)

**Interfaces:** consume `jerga launch` ya instalado en `~/.local/bin` (tras `./install.sh` o symlink para la prueba).

- [ ] **Paso 1: sección «Abrir apps y juegos» en SKILL.md** — contenido: `jerga launch <nombre>` es la vía directa para abrir apps y juegos (`--list [filtro]` para mirar, es libre); pedido explícito de abrir/lanzar → ejecutarlo sin pedir confirmación (la orden ya es el permiso, como transcribir), aunque arrancar cosas que NO te hayan pedido sigue siendo cambio con confirmación; ambiguo → una pregunta con las candidatas y, al contestar «la segunda», re-lanzar con `--pick 2`; tras lanzar → confirmar en una frase; Windows: el comando avisa de que aún no sabe, se lo dices. Cerrar apps/juegos sigue siendo delicado (trabajo sin guardar): fuera.
- [ ] **Paso 2: reinstalar y reiniciar** — `./install.sh` (o `uv sync` + symlink) y `jerga trinity restart` para que la skill se recargue.
- [ ] **Paso 3: verificación SIN lanzar nada** (regla: nada de arrancar apps en la máquina del usuario) — `jerga launch --list | head` devuelve nombres; la sección de la skill está en su sitio y no contradice el protocolo del paso 3 (la exención de confirmación es explícita para pedidos explícitos). La prueba de voz real («Trinity, ábreme Steam») queda a cargo del humano. Si se quiere validar el texto de la skill sin abrir nada, se puede leer el panel de Trinity tras `jerga order "¿qué harías si te pido que abras Steam?"` (pregunta, no ejecución) — solo si el humano lo autoriza.
- [ ] **Paso 4: suite completa** — `uv run pytest -q tests && uv run ruff check .`
- [ ] **Paso 5: commit** `Trinity: abre apps y juegos con jerga launch (sin confirmación si es pedido explícito)`

## Auto-revisión

- Cobertura spec: D1 (T1 dispatch/CLI), D2 (T1 escáner), D3 (T2 ejecución/env), D4 (T2 contrato/--pick), D5 (T3 skill), D6 (T1 stub win32), A1–A5 y A7–A8 (tests T1/T2), A6 (T3 verificación), restricciones (verde en cada commit).
- Foco de revisión: cada línea tiene su test asignado (1→T2 env, 2→T2 env, 3→T1 parse, 4→T2 match orden, 5→T2 exacto).
- Consistencia: `Candidate(folded=…)` se construye plegado en `collect()`; `match` nunca recomputa mal.
