#!/usr/bin/env bash
# nyx — instalador para Linux (Arch, Debian/Ubuntu, Fedora, openSUSE y derivadas).
#
#   curl -fsSL https://raw.githubusercontent.com/kcurtet/nyx/main/install.sh | bash
#   ./install.sh [--local] [--cpu] [--no-system] [--no-service] [--uninstall]
#
#   --local       instala desde este directorio (desarrollo) en vez de GitHub
#   --cpu         no instalar las librerías CUDA aunque haya GPU NVIDIA
#   --no-system   no tocar paquetes del sistema ni udev/grupos (sin sudo)
#   --no-service  no crear el servicio de systemd (arranque automático)
#   --uninstall   desinstalar
set -euo pipefail

REPO="https://github.com/kcurtet/nyx"
# NYX_HOME mueve la instalación; JERGA_HOME (override histórico) se respeta como fallback.
PREFIX="${NYX_HOME:-${JERGA_HOME:-$HOME/.local/share/nyx}}"
BIN="$HOME/.local/bin"
UNIT="$HOME/.config/systemd/user/nyx.service"
VIEJA_UNIT="$HOME/.config/systemd/user/jerga.service"
LOCAL=0 CPU=0 SYSTEM=1 SERVICE=1 UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --local) LOCAL=1 ;; --cpu) CPU=1 ;; --no-system) SYSTEM=0 ;;
    --no-service) SERVICE=0 ;; --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "opción desconocida: $a" >&2; exit 2 ;;
  esac
done

c_b=$'\e[1m' c_g=$'\e[32m' c_y=$'\e[33m' c_r=$'\e[31m' c_0=$'\e[0m'
step() { echo "${c_b}==>${c_0} $*"; }
warn() { echo "${c_y}  ! $*${c_0}"; }
die()  { echo "${c_r}  ✘ $*${c_0}" >&2; exit 1; }
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
USER="${USER:-$(id -un)}"

# ------------------------------------------------------------- desinstalar
if [ "$UNINSTALL" = 1 ]; then
  step "Desinstalando nyx"
  systemctl --user disable --now nyx.service 2>/dev/null || true
  systemctl --user disable --now jerga.service 2>/dev/null || true
  rm -f "$UNIT" "$BIN/nyx" "$BIN/jerga"
  rm -rf "$PREFIX"
  echo "Hecho. Se conservan tu config (~/.config/nyx), los modelos (~/.cache/huggingface)"
  echo "y la regla udev (/etc/udev/rules.d/80-nyx-uinput.rules; bórrala a mano si quieres)."
  exit 0
fi

[ "$(uname -s)" = Linux ] || die "Este instalador es para Linux. En Windows usa install.ps1."

# ------------------------------------------------------- paquetes sistema
. /etc/os-release 2>/dev/null || true
DISTRO=" ${ID:-} ${ID_LIKE:-} "
try_install() {  # instala paquetes de uno en uno, tolerando los que no existan
  local mgr="$1"; shift
  for p in "$@"; do
    case "$mgr" in
      pacman) $SUDO pacman -S --needed --noconfirm "$p" >/dev/null 2>&1 ;;
      apt)    $SUDO apt-get install -y -qq --no-install-recommends "$p" >/dev/null 2>&1 ;;
      dnf)    $SUDO dnf install -y -q "$p" >/dev/null 2>&1 ;;
      zypper) $SUDO zypper -q -n install "$p" >/dev/null 2>&1 ;;
    esac || warn "no se pudo instalar '$p' (opcional o con otro nombre en tu distro)"
  done
}

if [ "$SYSTEM" = 1 ]; then
  step "Instalando dependencias del sistema (${PRETTY_NAME:-desconocida})"
  case "$DISTRO" in
    *" arch "*|*" cachyos "*|*" manjaro "*|*" endeavouros "*)
      $SUDO pacman -S --needed --noconfirm python python-evdev python-gobject portaudio wl-clipboard xclip \
        || die "falló pacman"
      try_install pacman gtk4 gtk4-layer-shell tk
      # transcribir · audio del sistema · icono de bandeja · notificaciones · selector de ficheros
      try_install pacman ffmpeg libpulse libayatana-appindicator libnotify zenity ;;
    *" debian "*|*" ubuntu "*)
      $SUDO apt-get update -qq
      $SUDO apt-get install -y -qq --no-install-recommends python3 python3-venv python3-evdev python3-gi libportaudio2 wl-clipboard xclip \
        || die "falló apt"
      try_install apt gir1.2-gtk-4.0 gir1.2-gtk4layershell-1.0 libgtk4-layer-shell0 python3-tk
      try_install apt ffmpeg pulseaudio-utils gir1.2-ayatanaappindicator3-0.1 libnotify-bin zenity ;;
    *" fedora "*|*" rhel "*|*" centos "*)
      $SUDO dnf install -y -q python3 python3-evdev python3-gobject portaudio wl-clipboard xclip || die "falló dnf"
      try_install dnf gtk4 gtk4-layer-shell python3-tkinter
      command -v ffmpeg >/dev/null || try_install dnf ffmpeg-free
      try_install dnf pulseaudio-utils libayatana-appindicator-gtk3 libnotify zenity ;;
    *" opensuse"*|*" suse "*)
      $SUDO zypper -q -n install python3 python3-evdev python3-gobject portaudio wl-clipboard xclip || die "falló zypper"
      try_install zypper typelib-1_0-Gtk-4_0 gtk4-layer-shell typelib-1_0-Gtk4LayerShell-1_0 python3-tk
      command -v ffmpeg >/dev/null || try_install zypper ffmpeg-7
      try_install zypper pulseaudio-utils typelib-1_0-AyatanaAppIndicator3-0_1 libnotify-tools zenity ;;
    *)
      warn "distro no reconocida: instala a mano python3 (>=3.10, con venv), python-evdev, python-gobject,"
      warn "portaudio, wl-clipboard o xclip, ffmpeg; y opcionalmente gtk4-layer-shell o tk,"
      warn "parec (pulseaudio-utils), libayatana-appindicator, notify-send y zenity." ;;
  esac

  step "Permisos de teclado (tecla global + pegar en el cursor)"
  # /dev/uinput: teclado virtual para pulsar Shift+Insert, sin daemons extra.
  RULE='KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"'
  if [ ! -f /etc/udev/rules.d/80-nyx-uinput.rules ]; then
    $SUDO mkdir -p /etc/udev/rules.d /etc/modules-load.d
    echo "$RULE" | $SUDO tee /etc/udev/rules.d/80-nyx-uinput.rules >/dev/null
    echo uinput | $SUDO tee /etc/modules-load.d/nyx-uinput.conf >/dev/null
    $SUDO rm -f /etc/udev/rules.d/80-jerga-uinput.rules /etc/modules-load.d/jerga-uinput.conf
    $SUDO modprobe uinput 2>/dev/null || true
    $SUDO udevadm control --reload-rules 2>/dev/null && $SUDO udevadm trigger --name-match=uinput 2>/dev/null || true
  fi
  getent group input >/dev/null || $SUDO groupadd -r input
  if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    $SUDO usermod -aG input "$USER"
    NEED_RELOGIN=1
    warn "te he añadido al grupo 'input': cierra sesión y vuelve a entrar para que surta efecto."
    warn "Nota: el grupo 'input' permite leer cualquier teclado (es lo que necesita una tecla global en Wayland)."
  fi
fi

# ------------------------------------------------------------------ Python
PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "no encuentro python3"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "hace falta Python >= 3.10 ($("$PY" -V))"

step "Creando entorno en $PREFIX"
mkdir -p "$PREFIX" "$BIN"
# --system-site-packages: reutiliza python-gobject y python-evdev de la distro (no se compilan).
if command -v uv >/dev/null; then
  uv venv -q --allow-existing --system-site-packages --python "$PY" "$PREFIX/venv"
  PIP=(uv pip install -q --python "$PREFIX/venv/bin/python")
else
  "$PY" -m venv --system-site-packages "$PREFIX/venv" || die "falta python3-venv"
  "$PREFIX/venv/bin/python" -m pip install -q --upgrade pip
  PIP=("$PREFIX/venv/bin/python" -m pip install -q)
fi

EXTRA=""
if [ "$CPU" = 0 ] && command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
  EXTRA="[cuda]"; echo "   GPU NVIDIA detectada → se instalan cuBLAS/cuDNN"
else
  echo "   sin GPU NVIDIA (o --cpu) → Whisper en CPU"
fi
if [ "$LOCAL" = 1 ]; then
  SRC="$(cd "$(dirname "$0")" && pwd)"
  SPEC="nyx${EXTRA} @ file://$SRC"
else
  SPEC="nyx${EXTRA} @ git+$REPO"
fi
step "Instalando nyx ($SPEC)"
# Reinstala siempre nyx (para coger cambios) pero no sus dependencias.
if [ "${PIP[0]}" = uv ]; then
  "${PIP[@]}" --reinstall-package nyx "$SPEC" || die "falló la instalación de paquetes Python"
else
  "${PIP[@]}" "$SPEC" || die "falló la instalación de paquetes Python"
  "${PIP[@]}" --force-reinstall --no-deps "$SPEC" || die "falló reinstalando nyx"
fi
ln -sf "$PREFIX/venv/bin/nyx" "$BIN/nyx"
ln -sfn nyx "$BIN/jerga"  # alias de transición: mismo binario; nyx avisa del cambio UNA vez

# ------------------------------------------------------------- servicio
if [ "$SERVICE" = 1 ] && command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  step "Arranque automático (systemd --user)"
  if [ -f "$VIEJA_UNIT" ] || systemctl --user cat jerga.service >/dev/null 2>&1; then
    step "Retirando jerga.service (el nombre anterior)"
    systemctl --user disable --now jerga.service 2>/dev/null || true
    warn "jerga.service parado y desactivado (no se borra). Para purgarlo del todo:"
    warn "  rm ~/.config/systemd/user/jerga.service && systemctl --user daemon-reload"
  fi
  mkdir -p "$(dirname "$UNIT")"
  cat > "$UNIT" <<EOF
[Unit]
Description=nyx — dictado push-to-talk
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=$PREFIX/venv/bin/nyx
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable nyx.service >/dev/null 2>&1 || warn "no se pudo habilitar el servicio"
  if [ -z "${NEED_RELOGIN:-}" ]; then
    systemctl --user restart nyx.service || warn "no arrancó; mira: journalctl --user -u nyx"
  fi
fi

# ------------------------------------------------------------------ fin
step "Comprobando el equipo (nyx doctor)"
"$PREFIX/venv/bin/nyx" doctor || true
echo
echo "${c_g}${c_b}nyx instalado.${c_0}"
case ":$PATH:" in *":$BIN:"*) ;; *) warn "añade $BIN a tu PATH";; esac
echo "  Comprueba el equipo:  nyx doctor"
echo "  Configuración:        $("$PREFIX/venv/bin/nyx" config 2>/dev/null || echo "$HOME/.config/nyx/config.toml")"
echo "  Uso: mantén Ctrl derecho, habla y suelta. La 1ª vez descarga el modelo (~1.6 GB)."
echo "  Leer en voz alta: selecciona texto y pulsa Ctrl+0 (o di «léeme esto»)."
command -v ollama >/dev/null && ! ollama list 2>/dev/null | grep -q lfm3-omni && \
  echo "  Opcional, para nyx look (ver la pantalla): ollama pull lfm3-omni"
command -v herdr >/dev/null && echo "  Orquestadora por voz: nyx agent  (y luego «Trinity, …»)"
echo "  El alias jerga sigue funcionando (nyx te lo recuerda una vez); se retirará en una versión futura."
[ -n "${NEED_RELOGIN:-}" ] && echo "  ${c_y}Cierra sesión y vuelve a entrar antes de usarlo (grupo input).${c_0}"
true
