# Plan de implementación: herdr sin terminal abierta (spec 005)

> Ejecutar con la skill `executing-plans`, tarea a tarea. Pasos con checkbox `- [ ]`.

**Objetivo:** Nyx arranca `herdr server` headless bajo demanda, para que las órdenes por voz funcionen tras el login sin ninguna terminal abierta.

**Arquitectura:** todo vive en `nyx/orders.py`. El chequeo de disponibilidad pasa a mirar `herdr status --json` (no el rc), `_herdr()` normaliza cuerpos JSON de error como fallo, y una nueva `_ensure_herdr_server()` spawnea el servidor detached si hace falta. `choose_backend` integra el ensure con la semántica aprobada: `herdr` explícito sin fallback, `auto` con fallback a pi. `doctor` informa si él (vía choose_backend) arrancó el servidor.

**Stack:** Python 3.10+ (repo usa `from __future__ import annotations`), pytest + monkeypatch, ruff. Sin dependencias nuevas.

**Spec:** `docs/specs/005-herdr-sin-terminal/spec.md`

## Restricciones globales

- Solo `nyx/orders.py`, `nyx/doctor.py`, `nyx/config.py` (un comentario) y `tests/test_orders.py`.
- `uv run pytest -q tests` verde en Linux y Windows; `uvx ruff check .` limpio.
- Ningún test lanza un `herdr server` real: Popen y `_herdr` siempre fakeados (D3b).
- Con servidor ya corriendo, cero procesos nuevos (A3).
- `start_new_session` solo se pasa en POSIX (`start_new_session=os.name == "posix"`), para no discutir el comportamiento de Windows.

## Foco de revisión

1. `herdr status` rc 0 con servidor parado → hoy `herdr_available()` miente (A4). Test: T1.
2. CLI herdr rc 0 + `{"error":…}` → hoy `HerdrBackend.status()` devuelve `"unknown"` (no None) y `send()` calla el fallo (D4). Test: T2.
3. Sondeo sin deadline real: un herdr colgado estira el ensure a minutos (D2). Test: T3 usa timeout de sondeo corto y reloj, no contador de intentos.
4. Spawn doble por carrera o re-pick del supervisor (A3/A6). Test: T3 (running ya → sin spawn) y T4 (ensure sin memoizar).
5. Auto arrancando un servidor inútil en máquina sin pi (D3: pi primero). Test: T4 reusa `test_orquestador_sin_pi_dice_por_que`, que ya lo caza si se reordena.

---

### Tarea 1: chequeo real de disponibilidad (D1)

**Ficheros:**
- Modificar: `nyx/orders.py:137-138` (`herdr_available`)
- Test: `tests/test_orders.py`

**Interfaces:**
- Produce: `_herdr_server_running() -> bool` — True solo si `herdr status --json` responde rc 0 con `data["server"]["running"] is True`; si rc 0 pero el stdout no es JSON, fallback textual: línea `server:` seguida de `status: running`. rc != 0, excepción o timeout → False.
- Produce: `herdr_available() -> bool` = `shutil.which("herdr") is not None and _herdr_server_running()` (misma firma de hoy; los tests actuales la monkeypatchean).

- [ ] **Paso 1: test que falla** — en `tests/test_orders.py`:

```python
def test_herdr_available_mira_el_servidor_no_el_rc(monkeypatch):
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/herdr")
    # rc 0 pero servidor parado: hoy herdr_available() devuelve True (bug)
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (0, {"server": {"running": False}}, ""))
    assert o._herdr_server_running() is False
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (0, {"server": {"running": True}}, ""))
    assert o._herdr_server_running() is True
    assert o.herdr_available() is True

def test_herdr_server_running_fallback_textual(monkeypatch):  # A8: herdr viejo sin --json
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (0, None, "client:\n  v\n\nserver:\n  status: running\n"))
    assert o._herdr_server_running() is True
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (0, None, "server:\n  status: not running\n"))
    assert o._herdr_server_running() is False
```

- [ ] **Paso 2: ejecutar y verificar que falla**
Run: `uv run pytest tests/test_orders.py -k herdr_server_running -v`
Expected: FAIL — `AttributeError: ... has no attribute '_herdr_server_running'`
- [ ] **Paso 3: implementar `_herdr_server_running()` y reescribir `herdr_available()`** — el fallback textual solo aplica con rc 0 (hueco asumido en la spec D1).
- [ ] **Paso 4: ejecutar TODA la suite** — `uv run pytest -q tests` (los tests actuales monkeypathean `herdr_available`, así que no dependen de su interior; deben seguir verdes).
- [ ] **Paso 5: commit** `fix(orders): herdr_available mira server.running, no el exit code`

### Tarea 2: `_herdr` normaliza error-JSON como fallo (D4)

**Ficheros:**
- Modificar: `nyx/orders.py:44-61` (`_herdr`)
- Test: `tests/test_orders.py`

**Interfaces:**
- Modifica: `_herdr(*args, timeout=10) -> tuple[int, dict|None, str]` — si el JSON parseado tiene `"error"`, el rc devuelto pasa a 1; `data` se CONSERVA (diagnóstico, app.py).

- [ ] **Paso 1: test que falla**:

```python
def test_herdr_error_json_es_fallo():  # A5: rc 0 + {"error":…} → rc efectivo != 0
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R: returncode = 0; stdout = '{"id":"x","error":{"code":"server_not_running"}}'; stderr = ""
        return R()
    monkeypatch...  # igual que abajo: subprocess.run de o
```

Concreto: monkeypatch `o.subprocess.run` con un stub cuyo objeto respuesta tenga `.returncode=0`, `.stdout='{"id":"cli:agent:get","error":{"code":"server_not_running"}}'`, `.stderr=""`. Assert `o._herdr("agent", "get", "nyx-agent")` devuelve rc 1 y `data["error"]["code"] == "server_not_running"`. Y con stdout sin `"error"`, rc se conserva (0).

Además, test de regresión del comportamiento que esto repara:

```python
def test_herdr_status_none_con_servidor_caido(monkeypatch):
    # hoy: rc 0 + error JSON → status() devolvía "unknown" (lanzaba igual, send() callaba)
    monkeypatch.setattr(o, "_herdr", lambda *a, timeout=10: (1, {"error": {"code": "server_not_running"}}, ""))
    b = o.HerdrBackend({**CFG})
    assert b.status() is None
```

- [ ] **Paso 2: ejecutar y verificar que falla** — `uv run pytest tests/test_orders.py -k "error_json or servidor_caido" -v`; el segundo falla (devuelve `"unknown"`), el primero falla (rc 0).
- [ ] **Paso 3: implementar** — en `_herdr`, tras parsear `data`: `if data and "error" in data: rcode = 1` (variable local, no mutar `r.returncode`).
- [ ] **Paso 4: suite completa verde** (`uv run pytest -q tests`).
- [ ] **Paso 5: commit** `fix(orders): _herdr trata cuerpo {"error":…} como fallo (rc 1)`

### Tarea 3: arranque bajo demanda `_ensure_herdr_server()` (D2)

**Ficheros:**
- Modificar: `nyx/orders.py` (nueva función junto a `herdr_available`)
- Test: `tests/test_orders.py`

**Interfaces:**
- Consume: `_herdr_server_running()` (T1), `clean_child_env()`, `STATE_DIR` (global del módulo, monkeypatcheable), `log()`.
- Produce: `_ensure_herdr_server(timeout: float = 8.0) -> tuple[bool, str]` — (True, "") si el servidor acaba running; (False, motivo) si no. Efecto: como mucho UN `Popen([exe, "server"], stdin=DEVNULL, stdout=stderr=STATE_DIR/"herdr-server.log" (append), env=clean_child_env(), start_new_session=os.name == "posix")`. Pone a True el flag de módulo `_SERVER_STARTED_BY_NYX` solo cuando ella lo lanza (lo usa la T5).

- [ ] **Paso 1: tests que fallan** (fake `_herdr_server_running` + fake Popen que cuenta llamadas; NUNCA spawn real):

```python
def test_ensure_no_arranca_si_ya_running(monkeypatch):  # A3
    spawns = []
    monkeypatch.setattr(o, "_herdr_server_running", lambda: True)
    monkeypatch.setattr(o.subprocess, "Popen", lambda *a, **k: spawns.append(a) or _FakeProc())
    ok, why = o._ensure_herdr_server()
    assert ok and not spawns

def test_ensure_arranca_y_espera_running(monkeypatch):
    state = {"running": False, "spawns": 0}
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/herdr")
    monkeypatch.setattr(o, "_herdr_server_running", lambda: state["running"])
    monkeypatch.setattr(o.time, "sleep", lambda s: state.__setitem__("running", True))
    monkeypatch.setattr(o.subprocess, "Popen", lambda *a, **k: state.__setitem__("spawns", state["spawns"] + 1) or _FakeProc())
    monkeypatch.setattr(o, "STATE_DIR", tmp_path)
    ok, why = o._ensure_herdr_server()
    assert ok and state["spawns"] == 1 and o._SERVER_STARTED_BY_NYX

def test_ensure_agota_el_plazo_sin_running(monkeypatch):  # A2 (parte del mecanismo)
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/herdr")
    monkeypatch.setattr(o, "_herdr_server_running", lambda: False)
    monkeypatch.setattr(o.subprocess, "Popen", lambda *a, **k: _FakeProc())
    monkeypatch.setattr(o.time, "sleep", lambda s: None)   # sin dormir: deadline wall-clock corta
    monkeypatch.setattr(o.time, "monotonic", _reloj_rapido)  # avanza 1s por llamada → termina en ~8 vueltas
    ok, why = o._ensure_herdr_server()
    assert not ok and why
```

`_FakeProc`: objeto con `poll() -> None` y `wait()` (no usado). `_reloj_rapido`: contador que avanza 1.0 por llamada para que el bucle termine solo por deadline. Verificar en `test_ensure_arranca_y_espera_running` que el comando spawn fue `("/usr/bin/herdr", "server")` y que el log se abrió bajo el STATE_DIR fake.

- [ ] **Paso 2: ejecutar y verificar que fallan** — `uv run pytest tests/test_orders.py -k ensure -v`; FAIL: `AttributeError: _ensure_herdr_server`.
- [ ] **Paso 3: implementar `_ensure_herdr_server()`** — orden: running-check → `which` → Popen (log append, `start_new_session=os.name == "posix"`, flag `_SERVER_STARTED_BY_NYX = True`) → bucle `while time.monotonic() < deadline: if _herdr_server_running(): return True; time.sleep(0.25)` con sondeo `_herdr("status", "--json", timeout=2)` DENTRO de `_herdr_server_running` (T1 ya lo hace; no duplicar). El "already running" (Popen muere porque otro lo arrancó) no necesita caso especial: el bucle lo absorbe viendo running.
- [ ] **Paso 4: suite completa + ruff** — `uv run pytest -q tests && uvx ruff check .`
- [ ] **Paso 5: commit** `feat(orders): _ensure_herdr_server arranca herdr server headless bajo demanda`

### Tarea 4: integración en `choose_backend` (D3) y comentarios que dejan de mentir

**Ficheros:**
- Modificar: `nyx/orders.py:140-152` (`choose_backend`), docstring del módulo `nyx/orders.py:1-11`, comentario de `nyx/config.py:124-125`
- Test: `tests/test_orders.py` (rework de `test_eleccion_de_backend`)

**Interfaces:**
- Consume: `_ensure_herdr_server()` (T3).
- Produce: semántica nueva de `choose_backend(cfg) -> tuple[str|None, str]`: 1) sin pi → `(None, "…falta pi…")` sin tocar herdr; 2) `want="herdr"`: sin herdr instalado → `(None, "…no está instalado…")`; ensure falla → `(None, "…no he podido arrancar herdr…")` SIN fallback; 3) `want="auto"`: herdr instalado → ensure; ok → `("herdr","")`, fallo → `("pi","")`. Sin memoización de fallos.

- [ ] **Paso 1: rework del test existente + casos nuevos** (D3b: monkeypatch de `o._ensure_herdr_server`, nunca real):

```python
def test_eleccion_de_backend(monkeypatch):
    has = {"pi": True, "herdr": True, "ensure": True}
    monkeypatch.setattr(o.shutil, "which", lambda c: f"/usr/bin/{c}" if has.get(c) else None)
    monkeypatch.setattr(o, "_ensure_herdr_server", lambda timeout=8.0: (has["ensure"], ""))
    assert o.choose_backend(CFG) == ("herdr", "")
    has["ensure"] = False  # auto: ensure falla → pi, sin sermón
    assert o.choose_backend(CFG) == ("pi", "")
    has["herdr"] = False
    assert o.choose_backend(CFG) == ("pi", "")
    has["pi"] = False
    kind, why = o.choose_backend(CFG)          # pi primero: sin spawn inútil
    assert kind is None and "falta pi" in why

def test_backend_herdr_explicito_sin_fallback(monkeypatch):  # A2
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/c")
    monkeypatch.setattr(o, "_ensure_herdr_server", lambda timeout=8.0: (False, "herdr server no responde"))
    kind, why = o.choose_backend({**CFG, "backend": "herdr"})
    assert kind is None and "arrancar herdr" in why
    # y sin memoizar: el siguiente pick reintenta
    monkeypatch.setattr(o, "_ensure_herdr_server", lambda timeout=8.0: (True, ""))
    assert o.choose_backend({**CFG, "backend": "herdr"}) == ("herdr", "")

def test_backend_herdr_sin_instalar(monkeypatch):
    monkeypatch.setattr(o.shutil, "which", lambda c: "/usr/bin/pi" if c == "pi" else None)
    kind, why = o.choose_backend({**CFG, "backend": "herdr"})
    assert kind is None and "no está instalado" in why
```

`test_orquestador_sin_pi_dice_por_que` sigue tal cual (foca el orden pi-primero).

- [ ] **Paso 2: ejecutar y verificar que falla** — `uv run pytest tests/test_orders.py -k eleccion -v`; FAIL: choose_backend no llama a `_ensure_herdr_server` (monkeypatch sin efecto: devuelve herdr igual con ensure False).
- [ ] **Paso 3: implementar** la semántica D3 en `choose_backend`; actualizar docstring del módulo y el comentario de `nyx/config.py` (`# auto: herdr (lo arranca nyx si hace falta); si no puede, pi…`).
- [ ] **Paso 4: suite completa + ruff**.
- [ ] **Paso 5: commit** `feat(orders): choose_backend arranca herdr bajo demanda (auto con fallback a pi; herdr explícito sin fallback)`

### Tarea 5: doctor informa si arrancó el servidor (D5)

**Ficheros:**
- Modificar: `nyx/doctor.py:245-266` (sección órdenes por voz)
- Test: `tests/test_orders.py` (o `tests/test_doctor.py` si existe ya testeo de doctor; si no, se queda en test_orders con imports de doctor)

**Interfaces:**
- Consume: `o._SERVER_STARTED_BY_NYX` (T3), `choose_backend` (T4).
- Produce: una línea extra en la sección órdenes de `nyx doctor`: cuando el backend elegido es herdr y `_SERVER_STARTED_BY_NYX` está a True → `r.ok("herdr server arrancado por nyx", "estará en marcha aunque cierres todas las terminales")`.

- [ ] **Paso 1: test que falla** — llamar a la sección de doctor con fakes (`choose_backend` → `("herdr","")`, flag True) y assert de que la salida contiene "herdr server arrancado por nyx"; con flag False, que NO lo contiene.
- [ ] **Paso 2: ejecutar y verificar que falla** — expected FAIL: cadena ausente.
- [ ] **Paso 3: implementar** la línea condicional en `doctor.py`.
- [ ] **Paso 4: suite completa + ruff**.
- [ ] **Paso 5: commit** `feat(doctor): avisa cuando nyx ha arrancado herdr server`

---

## Verificación final (tras T5)

- `uv run pytest -q tests && uvx ruff check .` verde.
- Demo real (manual, con permiso del humano en su máquina): parar el servidor de herdr (`herdr server stop`), `systemctl --user restart nyx`, esperar ~25s (supervisor), `herdr workspace list` → aparece el workspace del agente con el servidor arrancado por nyx; `pgrep -af "herdr server"` muestra un proceso sin TTY. NO hacerlo sin avisar: mata los paneles vivos del usuario.

## Notas para el implementador

- No toques `HerdrBackend`/`PiRpcBackend`: solo `_herdr`, `herdr_available` (+ nueva `_herdr_server_running`), nueva `_ensure_herdr_server`, `choose_backend`, doctor y comentarios.
- `clean-tests`: un concepto por test, nombres en español como el resto del fichero.
- Si `herdr status --json` en tu máquina responde otra estructura, gana la spec (D1) — pero avísalo en el PR/commit.
