# Instala el clonador de voz (OmniVoice) en un entorno .venv dentro de esta carpeta.
# Uso: doble clic en instalar.bat, o desde PowerShell:  .\instalar.ps1  [-CPU]
param([switch]$CPU)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Paso($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }

# 1. Python 3.10 o superior
Paso "Buscando Python 3.10 o superior"
$pyExe = $null; $pyArgs = @()
foreach ($cand in @("py -3.14", "py -3.13", "py -3.12", "py -3.11", "py -3.10", "python")) {
    $partes = $cand.Split(" ")
    if (-not (Get-Command $partes[0] -ErrorAction SilentlyContinue)) { continue }
    $extra = @($partes | Select-Object -Skip 1)
    try {
        $v = & $partes[0] @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]"3.10") { $pyExe = $partes[0]; $pyArgs = $extra; break }
    } catch { }
}
if (-not $pyExe) {
    Write-Host "No encontré Python 3.10+. Instálalo desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH') y vuelve a correr esto." -ForegroundColor Red
    exit 1
}
Write-Host "Usando: $pyExe $pyArgs (Python $v)"

# 2. Entorno virtual
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Paso "Creando el entorno .venv"
    & $pyExe @pyArgs -m venv .venv
}
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet

# 3. PyTorch: con CUDA si hay tarjeta NVIDIA, si no, versión CPU
$hayNvidia = (-not $CPU) -and [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($hayNvidia) {
    Paso "Instalando PyTorch con CUDA (tarjeta NVIDIA detectada). Son ~3 GB, paciencia"
    & $vpy -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
} else {
    Paso "Instalando PyTorch para CPU (no hay NVIDIA o pediste -CPU). Va a funcionar, pero lento"
    & $vpy -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
}
if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de PyTorch." }

# 4. OmniVoice
Paso "Instalando OmniVoice"
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de OmniVoice." }

# 5. Descargar los modelos una vez, para que la app abra rápido y funcione sin internet
Paso "Descargando el modelo de voz k2-fsa/OmniVoice (~3 GB, solo la primera vez)"
& $vpy -c "from huggingface_hub import snapshot_download; snapshot_download('k2-fsa/OmniVoice')"
if ($LASTEXITCODE -ne 0) { throw "Falló la descarga del modelo." }
Paso "Descargando el transcriptor (~500 MB)"
& $vpy -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
if ($LASTEXITCODE -ne 0) { Write-Host "No se pudo bajar el transcriptor; el botón Transcribir lo intentará al usarlo." -ForegroundColor Yellow }

# 6. Comprobación
Paso "Comprobando"
& $vpy -c "import torch, omnivoice, gradio; print('torch', torch.__version__, '| gradio', gradio.__version__, '| GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no (CPU)')"
if ($LASTEXITCODE -ne 0) { throw "Algo quedó mal instalado." }

# 7. Acceso directo en el escritorio
try {
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Clonador de voz.lnk"
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sc.TargetPath = Join-Path $PSScriptRoot "abrir.bat"
    $sc.WorkingDirectory = $PSScriptRoot
    $sc.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,138"
    $sc.Save()
    Write-Host "Acceso directo creado en el escritorio: Clonador de voz"
} catch { }

Write-Host "`nListo! Abre el Clonador de voz desde el escritorio o con abrir.bat." -ForegroundColor Green
