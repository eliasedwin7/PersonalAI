# ==========================================
# PersonalAI Installer (Anaconda Version)
#
# Creates the "personalai" conda env and installs the app into it, editable.
# Run from an Anaconda Prompt (so `conda` is on PATH):
#   powershell -ExecutionPolicy Bypass -File Install-PersonalAI-Env.ps1
# Add -Dev to also install pytest/ruff:
#   powershell -ExecutionPolicy Bypass -File Install-PersonalAI-Env.ps1 -Dev
# Safe to re-run: every step skips work that is already done.
#
# This installs PersonalAI itself, NOT Ollama - Ollama is a separate
# program you install once from ollama.com (see SETUP.md). PersonalAI
# just talks to it over HTTP; it has almost no dependencies of its own.
# ==========================================

param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$EnvName = "personalai"

Write-Host "===== PersonalAI Conda Installer ====="

try { conda --version | Out-Null }
catch {
    Write-Host "ERROR: conda not found in PATH."
    Write-Host "Install Anaconda (anaconda.com/download), then run this from an Anaconda Prompt."
    exit 1
}

$envExists = conda env list | Select-String "^$EnvName\s"
if (!$envExists) {
    Write-Host "Creating conda environment '$EnvName' (python 3.11)..."
    conda create -n $EnvName python=3.11 -y
} else {
    Write-Host "Conda env '$EnvName' already exists - skipping create."
}

$envPython = (conda run -n $EnvName python -c "import sys; print(sys.executable)").Trim()
if (!(Test-Path $envPython)) {
    Write-Host "ERROR: could not resolve python inside env '$EnvName'."
    exit 1
}
Write-Host "Using python: $envPython"

Write-Host "Installing runtime requirements..."
& $envPython -m pip install -r "$PSScriptRoot\requirements.txt"

if ($Dev) {
    Write-Host "Installing dev requirements (pytest, ruff)..."
    & $envPython -m pip install -r "$PSScriptRoot\requirements-dev.txt"
}

Write-Host "Installing personalai (editable)..."
& $envPython -m pip install -e "$PSScriptRoot"

Write-Host ""
Write-Host "Checking for a running Ollama server (optional at this point)..."
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 -UseBasicParsing | Out-Null
    Write-Host "  Ollama is reachable - you're ready to go."
} catch {
    Write-Host "  Ollama not found at http://127.0.0.1:11434 - that's fine for now."
    Write-Host "  Install it from ollama.com and 'ollama pull llama3.1' before your first chat."
    Write-Host "  See SETUP.md for details."
}

Write-Host ""
Write-Host "===== Done ====="
Write-Host "Try it: conda run -n $EnvName myai chat `"hello`""
Write-Host "Or double-click Run-PersonalAI.bat for an interactive session."
