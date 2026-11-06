# nyx — instalador para Windows 10/11
#
#   irm https://raw.githubusercontent.com/kcurtet/nyx/main/install.ps1 | iex
#   .\install.ps1 [-Cpu] [-NoStartup] [-Local] [-Uninstall]
#
#   -Cpu        no instalar las librerías CUDA aunque haya GPU NVIDIA
#   -NoStartup  no arrancar nyx con Windows
#   -Local      instalar desde esta carpeta (desarrollo) en vez de GitHub
#   -Uninstall  desinstalar
#   -NoRun      no arrancar nyx al terminar (CI)
param([switch]$Cpu, [switch]$NoStartup, [switch]$Local, [switch]$Uninstall, [switch]$NoRun)
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/kcurtet/nyx"
$Startup = Join-Path ([Environment]::GetFolderPath("Startup")) "nyx.lnk"

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

# uv: gestiona Python y el entorno aislado de nyx
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Step "Instalando uv"
    powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if ($Uninstall) {
    Step "Desinstalando nyx"
    uv tool uninstall nyx
    Remove-Item $Startup -ErrorAction SilentlyContinue
    $oldAlias = Join-Path (uv tool dir --bin).Trim() "jerga.cmd"
    Remove-Item $oldAlias -ErrorAction SilentlyContinue
    Write-Host "Hecho. Se conservan tu config (%APPDATA%\nyx) y los modelos (~\.cache\huggingface)."
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
    $spec = "nyx$extra @ file:///$src"
} else {
    $spec = "nyx$extra @ git+$Repo"
}

# ffmpeg: necesario para transcribir audio/vídeo (nyx transcribe, notas de voz)
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Step "Instalando ffmpeg (winget)"
        winget install --id Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    } else {
        Write-Host "   ! sin ffmpeg: nyx transcribe no funcionará (instálalo y añádelo al PATH)" -ForegroundColor Yellow
    }
}

Step "Instalando nyx ($spec)"
uv tool install --force --python 3.12 $spec
if ($LASTEXITCODE -ne 0) { throw "falló uv tool install" }
uv tool update-shell | Out-Null

$binDir = (uv tool dir --bin).Trim()
$gui = Join-Path $binDir "nyx-gui.exe"

# Alias de transición: jerga.cmd llama a nyx.exe marcando NYX_ALIAS para que nyx avise
# del cambio de nombre UNA sola vez (spec 003, D3). Se retirará en una versión futura.
$alias = Join-Path $binDir "jerga.cmd"
@'
@echo off
set "NYX_ALIAS=jerga"
"%~dp0nyx.exe" %*
'@ -replace "`n", "`r`n" | Set-Content -Path $alias -Encoding ascii

if (-not $NoStartup) {
    Step "Arranque automático con Windows"
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($Startup)
    $sh.TargetPath = $gui
    $sh.Description = "nyx - dictado push-to-talk"
    $sh.Save()
}

if (-not $NoRun) {
    Step "Arrancando nyx"
    Start-Process $gui
}

Write-Host ""
Write-Host "nyx instalado." -ForegroundColor Green
Write-Host "  Comprueba el equipo:  nyx doctor   (abre una terminal nueva)"
Write-Host "  Configuracion:        nyx config"
Write-Host "  Log:                  %LOCALAPPDATA%\nyx\nyx.log"
Write-Host "  Uso: mantén Ctrl derecho, habla y suelta. La 1a vez descarga el modelo (~1.6 GB)."
Write-Host "  Leer en voz alta: selecciona texto y pulsa Ctrl+0."
Write-Host "  El alias jerga sigue funcionando (jerga.cmd); se retirará en una versión futura."
& (Join-Path $binDir "nyx.exe") doctor
$global:LASTEXITCODE = 0  # el doctor es informativo: no fallar la instalación por un aviso
