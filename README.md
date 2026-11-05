# jerga

**Dictado que entiende tu jerga.** Habla en español, di `git push`, `docker compose` o `pull request`, y aparece bien escrito donde tengas el cursor.

Mantén **Ctrl derecho** → habla → suelta. Todo en local, con Whisper en tu GPU (o CPU).

```
 ● ▁▃▅▇▅▃▁▂▄  0:03        mientras hablas
 ● ∿∿∿∿∿∿∿∿  transcribiendo
 ● haz un git push a main y levanta el docker compose
```

## Por qué

Los dictados normales destrozan el español técnico: *"haz un guit pus"*, *"levanta el dóquer con pose"*. jerga lo ataca en capas:

1. **Whisper large-v3-turbo** con tu **vocabulario técnico en el prompt** → la mayor mejora.
2. **Reemplazos** deterministas para los errores que se repitan (`"dóquer" = "Docker"`).
3. **LLM local opcional** (Ollama) que corrige solo términos técnicos.

## Instalación

### Linux (Arch, Debian/Ubuntu, Fedora, openSUSE y derivadas)

```sh
curl -fsSL https://raw.githubusercontent.com/kcurtet/jerga/main/install.sh | bash
```

Instala dependencias del sistema (pide `sudo`), crea un entorno en `~/.local/share/jerga`, el comando `jerga` en `~/.local/bin`, y un servicio de systemd para que arranque con tu sesión. Si detecta GPU NVIDIA instala CUDA.

> **Grupo `input`:** para una tecla global en Wayland jerga lee el teclado directamente (`/dev/input`), y pulsa Shift+Insert con un teclado virtual (`/dev/uinput`). El instalador te añade al grupo `input` y crea una regla udev. Ten en cuenta que ese grupo permite leer cualquier teclado. **Cierra sesión y vuelve a entrar** tras instalar.
>
> Si no quieres eso: `./install.sh --no-system` y lanza `jerga toggle` desde un atajo de teclado de tu escritorio.

Opciones: `--cpu` (sin CUDA), `--no-service`, `--no-system`, `--uninstall`.

### Windows 10/11 (experimental)

En PowerShell:

```powershell
irm https://raw.githubusercontent.com/kcurtet/jerga/main/install.ps1 | iex
```

Usa [uv](https://docs.astral.sh/uv/) para instalar Python y jerga, y lo añade al inicio de Windows. Opciones: `-Cpu`, `-NoStartup`, `-Uninstall`.

### Comprobar

```sh
jerga doctor
```

Revisa GPU, micrófono, tecla global, portapapeles y widget, y dice cómo arreglar lo que falte.

## Uso

| | |
|---|---|
| Mantener **Ctrl derecho** | grabar; al soltar, transcribe y pega |
| Ctrl derecho + otra tecla | cancela (era un atajo, no dictado) |
| `jerga toggle` / `start` / `stop` / `cancel` | control desde atajos del escritorio o scripts |
| `jerga keys` | muestra el nombre de las teclas que pulses (para cambiar la tecla) |
| `jerga config` | ruta del archivo de configuración |

La primera vez descarga el modelo (~1.6 GB).

## Comandos de voz

Palabras que no se escriben, sino que hacen algo. Se ignoran tildes y mayúsculas, y se pueden encadenar (*"…interrogante envía"*).

| Dices | Resultado |
|---|---|
| *"has hecho el push **interrogante**"* | ¿Has hecho el push? |
| *"ya pasa el build **exclamación**"* | ¡Ya pasa el build! |
| *"revisa los logs **envía**"* | pega y pulsa **Enter** (ideal para chats y agentes) |
| *"… **borra eso**"* | no pega nada |
| *"**código** git status"* | `` `git status` `` |
| *"hola mundo **entre comillas**"* | "hola mundo" |
| *"feature login **en minúsculas**"* | feature login |
| *"… **nueva línea** …"* / *"… **punto y aparte** …"* | salto de línea |

Los comandos de final de frase solo actúan **al final**: *"borra eso del config"* se escribe normal. Cambia o desactiva las palabras en `[commands]`.

## Configuración

`~/.config/jerga/config.toml` (Windows: `%APPDATA%\jerga\config.toml`). Reinicia tras editar (`systemctl --user restart jerga`).

- **`stt.vocabulary`** — términos que Whisper debe esperar, escritos como quieres verlos. *La palanca más efectiva: añade tus herramientas, proyectos y comandos.*
- **`[replacements]`** — correcciones exactas para errores recurrentes. Mira el log para encontrarlos.
- **`[llm]`** — segunda pasada con Ollama. Desactivada por defecto: rápida (~0.15 s con `qwen2.5:3b`) pero a veces inventa.
- **`hotkey.key`** / **`hotkey.mode`** — tecla y modo `hold` (mantener) o `toggle`.
- **`output.paste_keys`** — `shift+insert` (Linux) / `ctrl+v` (Windows). Cambia a `ctrl+shift+v` si tu terminal no pega.
- **`stt.model`** — sin GPU, si va lento, prueba `"small"` o `"medium"`.

Log: `journalctl --user -u jerga -f` o `~/.local/state/jerga/jerga.log` (Windows: `%LOCALAPPDATA%\jerga\jerga.log`).

## Compatibilidad

| | Tecla global | Pegar | Widget |
|---|---|---|---|
| KDE Plasma (Wayland) | evdev | uinput + wl-clipboard | GTK4 layer-shell ✅ probado |
| Sway, Hyprland, wlroots | evdev | uinput + wl-clipboard | GTK4 layer-shell |
| GNOME (Wayland) | evdev | uinput + wl-clipboard | Tk vía XWayland |
| X11 (cualquier escritorio) | evdev | uinput + xclip | Tk |
| Windows 10/11 | pynput | Ctrl+V | Tk |

El instalador de Linux está probado en Arch/CachyOS, Debian 13, Ubuntu 24.04, Fedora 43 y openSUSE Tumbleweed.

## Desarrollo

```sh
git clone https://github.com/kcurtet/jerga && cd jerga
./install.sh --local      # instala desde el directorio actual
```

Estructura: `jerga/stt.py` (Whisper), `postprocess.py` (reemplazos + LLM), `output.py` (portapapeles + teclas por plataforma), `hotkey.py` (tecla global + control), `ui/` (widgets), `doctor.py`.
