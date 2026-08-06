param(
    [switch]$Setup
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root ".venv-desktop\Scripts\python.exe"

Set-Location $Root

if ($Setup -or -not (Test-Path $VenvPython)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "No se encontro el Python launcher 'py'. Instala Python o ejecuta el build desde un entorno activo."
    }

    py -3.11 -m venv ".venv-desktop"
    if ($LASTEXITCODE -ne 0) {
        py -3 -m venv ".venv-desktop"
    }
}

& $VenvPython -m pip install --disable-pip-version-check --only-binary=:all: -r "requirements-desktop.txt"
& $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name "MazzorisBancos" `
    --hidden-import "openpyxl" `
    "desktop_banks_app.py"

Write-Host "Portable listo en dist\MazzorisBancos\MazzorisBancos.exe"
