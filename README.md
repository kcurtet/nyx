# voice-agent

Dictado local para programadores hispanohablantes: mantén **Ctrl derecho**, habla, suelta → el texto aparece donde tengas el cursor (terminal, pi, navegador, documentos…).

Pipeline: `evdev hotkey → micrófono → faster-whisper (GPU) + vocabulario → reemplazos → [LLM opcional] → wl-copy + ydotool (shift+insert)`

Widget: píldora GTK4 + layer-shell abajo al centro; nunca roba el foco.

## Uso

```sh
./voice-agent            # arranca (tarda ~10 s en cargar el modelo)
./voice-agent toggle     # start | stop | toggle | cancel  (para atajos de KDE)
./voice-agent keys       # muestra el nombre evdev de las teclas que pulses
```

Atajo alternativo en KDE: *Ajustes → Atajos → Añadir comando* → `~/dev/voice-agent/voice-agent toggle`.

Mantener Ctrl derecho + otra tecla (Ctrl+C…) cancela la grabación, así no interfiere con atajos.

## Configuración

`~/.config/voice-agent/config.toml` (se crea desde `config.example.toml`):

- `stt.vocabulary` — términos que Whisper debe esperar (va al prompt inicial). **La palanca más efectiva.**
- `[replacements]` — correcciones exactas para errores que se repiten (`"dóquer" = "Docker"`).
- `[llm]` — segunda pasada con Ollama. Desactivada por defecto: rápida (~0.15 s con qwen2.5:3b) pero a veces inventa.
- `output.paste_keys` — `shift+insert` por defecto; cambia a `ctrl+shift+v` si tu terminal no lo pega.

Reinicia tras editar.

## Autoarranque

```sh
mkdir -p ~/.config/systemd/user
cp voice-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now voice-agent
journalctl --user -u voice-agent -f   # ver transcripciones y errores
```

## Requisitos (ya presentes en este equipo)

KDE Wayland, `ydotoold` activo, usuario en grupo `input`, `gtk4-layer-shell`, `python-gobject`, `python-evdev`, `wl-clipboard`, GPU NVIDIA.
Venv: `uv venv --system-site-packages --python /usr/bin/python3 .venv && uv pip install --python .venv/bin/python faster-whisper sounddevice numpy httpx "av>=13" nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"`
