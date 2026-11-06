# jerga — instalador para Windows 10/11
#
#   irm https://raw.githubusercontent.com/kcurtet/jerga/main/install.ps1 | iex
#   .\install.ps1 [-Cpu] [-NoStartup] [-Local] [-Uninstall]
#
#   -Cpu        no instalar las librerías CUDA aunque haya GPU NVIDIA
#   -NoStartup  no arrancar jerga con Windows
#   -Local      instalar desde esta carpeta (desarrollo) en vez de GitHub
#   -Uninstall  desinstalar
#   -NoRun      no arrancar jerga al terminar (CI)
param([switch]$Cpu, [switch]$NoStartup, [switch]$Local, [switch]$Uninstall, [switch]$NoRun)
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/kcurtet/jerga"
$Startup = Join-Path ([Environment]::GetFolderPath("Startup")) "jerga.lnk"

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

# uv: gestiona Python y el entorno aislado de jerga
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Step "Instalando uv"
    powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if ($Uninstall) {
    Step "Desinstalando jerga"
    uv tool uninstall jerga
    Remove-Item $Startup -ErrorAction SilentlyContinue
    Write-Host "Hecho. Se conservan tu config (%APPDATA%\jerga) y los modelos (~\.cache\huggingface)."
    exit 0
}

$extra = ""
if (-not $Cpu -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    $extra = "[cuda]"
    Write-Host "   GPU NVIDIA detectada -> se instalan cuBLAS/cuDNN"
} else {
    Write-Host "   sin GPU NVIDIA (o -Cpu) -> Whisper en CPU"
}

if ($Local) {
    $src = (Resolve-Path $PSScriptRoot).Path -replace '\\', '/'
    $spec = "jerga$extra @ file:///$src"
} else {
    $spec = "jerga$extra @ git+$Repo"
}

# ffmpeg: necesario para transcribir audio/vídeo (jerga transcribe, notas de voz)
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Step "Instalando ffmpeg (winget)"
        winget install --id Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    } else {
        Write-Host "   ! sin ffmpeg: jerga transcribe no funcionará (instálalo y añádelo al PATH)" -ForegroundColor Yellow
    }
}

Step "Instalando jerga ($spec)"
uv tool install --force --python 3.12 $spec
if ($LASTEXITCODE -ne 0) { throw "falló uv tool install" }
uv tool update-shell | Out-Null

$binDir = (uv tool dir --bin).Trim()
$gui = Join-Path $binDir "jerga-gui.exe"

if (-not $NoStartup) {
    Step "Arranque automático con Windows"
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($Startup)
    $sh.TargetPath = $gui
    $sh.Description = "jerga - dictado push-to-talk"
    $sh.Save()
}

if (-not $NoRun) {
    Step "Arrancando jerga"
    Start-Process $gui
}

Write-Host ""
Write-Host "jerga instalado." -ForegroundColor Green
Write-Host "  Comprueba el equipo:  jerga doctor   (abre una terminal nueva)"
Write-Host "  Configuracion:        jerga config"
Write-Host "  Log:                  %LOCALAPPDATA%\jerga\jerga.log"
Write-Host "  Uso: mantén Ctrl derecho, habla y suelta. La 1a vez descarga el modelo (~1.6 GB)."
Write-Host "  Leer en voz alta: selecciona texto y pulsa Ctrl+0."
& (Join-Path $binDir "jerga.exe") doctor
