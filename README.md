# nyx

     \\
     (o>
    //\\

[![CI](https://github.com/kcurtet/nyx/actions/workflows/ci.yml/badge.svg)](https://github.com/kcurtet/nyx/actions/workflows/ci.yml) [![Instalación](https://github.com/kcurtet/nyx/actions/workflows/install.yml/badge.svg)](https://github.com/kcurtet/nyx/actions/workflows/install.yml)

**Dictado que entiende tu jerga técnica.** Habla en español, di `git push`, `docker compose` o `pull request`, y aparece bien escrito donde tengas el cursor.

Mantén **Ctrl derecho** → habla → suelta. Todo en local, con Whisper en tu GPU (o CPU).

```
 ● ▁▃▅▇▅▃▁▂▄  0:03        mientras hablas
 ● ∿∿∿∿∿∿∿∿  transcribiendo
 ● haz un git push a main y levanta el docker compose
```

> Antes se llamaba `jerga`: el alias sigue funcionando un tiempo y te avisa la primera vez.

## Por qué

Los dictados normales destrozan el español técnico: *"haz un guit pus"*, *"levanta el dóquer con pose"*. nyx lo ataca en capas:

1. **Whisper large-v3-turbo** con tu **vocabulario técnico en el prompt** → la mayor mejora.
2. **Reemplazos** deterministas para los errores que se repitan (`"dóquer" = "Docker"`).
3. **LLM local opcional** (Ollama) que corrige solo términos técnicos.

## Instalación

### Linux (Arch, Debian/Ubuntu, Fedora, openSUSE y derivadas)

```sh
curl -fsSL https://raw.githubusercontent.com/kcurtet/nyx/main/install.sh | bash
```

Instala dependencias del sistema (pide `sudo`), crea un entorno en `~/.local/share/nyx`, el comando `nyx` en `~/.local/bin`, y un servicio de systemd para que arranque con tu sesión. Si detecta GPU NVIDIA instala CUDA.

> **Grupo `input`:** para una tecla global en Wayland nyx lee el teclado directamente (`/dev/input`), y pulsa Shift+Insert con un teclado virtual (`/dev/uinput`). El instalador te añade al grupo `input` y crea una regla udev. Ten en cuenta que ese grupo permite leer cualquier teclado. **Cierra sesión y vuelve a entrar** tras instalar.
>
> Si no quieres eso: `./install.sh --no-system` y lanza `nyx toggle` desde un atajo de teclado de tu escritorio.

Opciones: `--cpu` (sin CUDA), `--no-service`, `--no-system`, `--uninstall`.

### Windows 10/11 (experimental)

En PowerShell:

```powershell
irm https://raw.githubusercontent.com/kcurtet/nyx/main/install.ps1 | iex
```

Usa [uv](https://docs.astral.sh/uv/) para instalar Python y nyx, y lo añade al inicio de Windows. Opciones: `-Cpu`, `-NoStartup`, `-Uninstall`.

### Comprobar

```sh
nyx doctor
```

Revisa GPU, micrófono, tecla global, portapapeles y widget, y dice cómo arreglar lo que falte.

## Uso

| | |
|---|---|
| Mantener **Ctrl derecho** | grabar; al soltar, transcribe y pega |
| Ctrl derecho + otra tecla | cancela (era un atajo, no dictado) |
| **Ctrl+0** o «léeme esto» | lee el texto seleccionado (otra vez, o «calla»: se calla) |
| `nyx toggle` / `start` / `stop` / `cancel` | control del dictado desde atajos o scripts |
| `nyx say "…"` / `nyx hush` | leer texto en voz alta / callar |
| `nyx launch "steam"` | abre una app o juego instalado (`--list` para ver los nombres) |
| `nyx vol [30]` | volumen del sistema: `up`, `down`, `mute` o porcentaje |
| `nyx remind "apagar el fuego" en 20m` | recordatorio one-shot con aviso y voz (`18:00` también; `--list`, `--cancel N`) |
| `nyx keys` | muestra el nombre de las teclas que pulses (para cambiar la tecla) |
| `nyx config` | ruta del archivo de configuración |

La primera vez descarga el modelo (~1.6 GB).

## Leer en voz alta

Selecciona texto en cualquier sitio y pulsa **Ctrl+0** (o di «léeme esto»). Otra vez, se calla; si empiezas a dictar, también.

```sh
nyx say "El pipeline del CI/CD ya pasa"   # o: echo "…" | nyx say
nyx hush                                  # callar
```

Voz local con [phonon](https://huggingface.co/gradium/phonon-40m-es) (40M parámetros, CPU, empieza a hablar en ~0,4 s). Antes de leer:

- **Normaliza texto técnico:** no lee bloques de código ("Bloque de código en python"), quita Markdown y emojis, resume URLs ("un enlace a github.com") y rutas (`/etc/x/y.conf` → "y.conf").
- **Lexicón de pronunciación** afinado a oído: `kubectl` → *kiub ci ti el*, `el CI/CD` → *la integración continua*, `pipeline` → *paip-láin*… Amplíalo en `[tts.lexicon]`.

Si tienes Ctrl y Bloq Mayús intercambiados (`ctrl:swapcaps`, `ctrl:nocaps`…), nyx lo detecta en KDE, GNOME y wlroots: tu "Ctrl" funciona en los atajos. Si no, indícalo en `[hotkey] ctrl_keys`.

`nyx say` sirve para que otros programas hablen; por ejemplo, un agente que lea sus respuestas.

## Transcribir audio y vídeo

```sh
nyx transcribe reunion.mp4                 # → reunion.md con marcas de tiempo
nyx transcribe nota.ogg --format srt       # o txt; --out DIR; --stdout
```

Cualquier formato que lea ffmpeg (mp3, ogg/opus de WhatsApp, m4a, mp4, mkv…), con tu vocabulario técnico y tus reemplazos. Los ficheros de más de 10 min se procesan en bloques de ~5 min cortados en silencios (con el final del bloque anterior como contexto): el `.md` va apareciendo por partes, Whisper no entra en bucle y **tu dictado pasa delante** entre bloques (`[transcribe]` long_after_s / block_s). Usa el Whisper que ya tiene cargado el servicio: 34 s de audio en ~0,7 s en GPU. También desde el icono de la bandeja → *Transcribir fichero…*

### Sesiones largas en vivo

```sh
nyx record              # micrófono
nyx record --system     # lo que suena en el PC (una llamada, un vídeo, un curso)
nyx record --both       # los dos: sale etiquetado «Yo:» / «Ellos:»
nyx record stop         # termina y te dice dónde está el .md
```

Trocea en silencios (~25 s), transcribe con el Whisper del servicio y reescribe el `.md` tras cada trozo: puedes abrirlo mientras graba. Por defecto en `~/Documentos/nyx/`. Con `--both` usa auriculares (si no, el micro también recoge lo que suena). Ignora el silencio para que Whisper no se invente frases.

### Notas de voz

Deja una nota de voz (`.ogg`, `.opus`, `.m4a`) en **`~/Documentos/nyx/notas`** y se transcribe sola: el `.md` queda al lado y te llega una notificación con el principio del texto. Solo esa carpeta (no Descargas: ahí cae de todo); puedes añadir otras en `[notes] dirs`.

## Icono en la bandeja

El servicio pone un micrófono en la bandeja del sistema que cambia de color: **gris** listo · **rojo** grabando · **azul** trabajando · **morado** leyendo · **naranja** sin servicio. Menú: dictar, leer selección/callar, transcribir fichero, Nyx, configuración, log y reiniciar. Desactívalo con `[tray] enabled = false`.

## Nyx: órdenes por voz

Empieza el dictado con **"Nyx, …"** y no se pega: va a una orquestadora (pi en una pestaña de [herdr](https://herdr.dev)) que maneja tus repos, terminales y agentes de pi o Claude.

```sh
nyx agent                          # arrancarla (una vez)
# Ctrl derecho: «Nyx, ve al repo nyx y cambia la imagen del README por la que tengo en descargas»
nyx order "¿qué hace el agente de screeps?"   # lo mismo, por texto
```

- Pregunta si algo es ambiguo y **pide confirmación antes de cambiar nada**; tú contestas igual: «Nyx, sí».
- Responde **en voz alta** (1-2 frases; el detalle queda en su panel) y avisa si el modelo falla.
- **Ve tu pantalla** con un modelo de visión local: `nyx look "¿qué error sale?"` (lfm3-omni vía Ollama).

Configuración en `[orders]` (palabra de activación, modelo de pi) y `[vision]`.

## Comandos de voz

Palabras que no se escriben, sino que hacen algo. Se ignoran tildes y mayúsculas, y se pueden encadenar (*"…interrogante envía"*).

| Dices | Resultado |
|---|---|
| *"has hecho el push **interrogante**"* | ¿Has hecho el push? |
| *"ya pasa el build **exclamación**"* | ¡Ya pasa el build! |
| *"revisa los logs **envía**"* | pega y pulsa **Enter** (ideal para chats y agentes) |
| *"… **borra eso**"* | no pega nada |
| *"**código** git status"* | `` `git status` `` |
| *"**ruta** tilde barra dev barra nyx punto md"* | `~/dev/nyx.md` (paths: símbolos hablados pegados; «espacio» = espacio real) |
| *"hola mundo **entre comillas**"* | "hola mundo" |
| *"pon commit **KX minúsculas**"* | pon commit kx (minusculiza la palabra anterior) |
| *"… **nueva línea** …"* / *"… **punto y aparte** …"* | salto de línea |

Los comandos de final de frase solo actúan **al final**: *"borra eso del config"* se escribe normal. Cambia o desactiva las palabras en `[commands]`.

## Configuración

`~/.config/nyx/config.toml` (Windows: `%APPDATA%\nyx\config.toml`). Reinicia tras editar (`systemctl --user restart nyx`).

- **`stt.vocabulary`** — términos que Whisper debe esperar, escritos como quieres verlos. *La palanca más efectiva: añade tus herramientas, proyectos y comandos.*
- **`[replacements]`** — correcciones exactas para errores recurrentes. Mira el log para encontrarlos.
- **`[llm]`** — segunda pasada con Ollama. Desactivada por defecto: rápida (~0.15 s con `qwen2.5:3b`) pero a veces inventa.
- **`hotkey.key`** / **`hotkey.mode`** — tecla y modo `hold` (mantener) o `toggle`.
- **`output.paste_keys`** — `shift+insert` (Linux) / `ctrl+v` (Windows). Cambia a `ctrl+shift+v` si tu terminal no pega.
- **`stt.model`** — sin GPU, si va lento, prueba `"small"` o `"medium"`.

Log: `journalctl --user -u nyx -f` o `~/.local/state/nyx/nyx.log` (Windows: `%LOCALAPPDATA%\nyx\nyx.log`).

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
git clone https://github.com/kcurtet/nyx && cd nyx
./install.sh --local      # instala desde el directorio actual
```

Estructura: `nyx/stt.py` (Whisper), `postprocess.py` (reemplazos + LLM), `output.py` (portapapeles + teclas por plataforma), `hotkey.py` (tecla global + control), `ui/` (widgets), `doctor.py`.
