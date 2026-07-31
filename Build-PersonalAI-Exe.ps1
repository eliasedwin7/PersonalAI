# ==========================================
# Nexus - PyInstaller build (one-folder, windowed)
#
# Run from an Anaconda Prompt:
#   powershell -ExecutionPolicy Bypass -File Build-PersonalAI-Exe.ps1
#   powershell -ExecutionPolicy Bypass -File Build-PersonalAI-Exe.ps1 -Shortcut
#
# Produces dist\Nexus\Nexus.exe - double-click it, no conda or
# terminal needed. -Shortcut also drops a "Nexus" shortcut on your
# Desktop pointing at it.
# ==========================================

param(
    [switch]$Shortcut
)

$ErrorActionPreference = "Stop"
$EnvName = "personalai"

Write-Host "===== Nexus Exe Builder ====="

try { conda --version | Out-Null }
catch {
    Write-Host "ERROR: conda not found in PATH. Run from an Anaconda Prompt."
    exit 1
}

$envPython = (conda run -n $EnvName python -c "import sys; print(sys.executable)").Trim()
if ([string]::IsNullOrWhiteSpace($envPython)) {
    # Conda can occasionally return no captured stdout when this script is
    # launched from another PowerShell host. The standard named-environment
    # location is a reliable fallback, and still gets checked below.
    $condaBase = (conda info --base).Trim()
    $envPython = Join-Path $condaBase "envs\$EnvName\python.exe"
}
if (!(Test-Path $envPython)) {
    Write-Host "ERROR: env '$EnvName' not found - run Install-PersonalAI-Env.ps1 first."
    exit 1
}

Write-Host "Installing voice extras + PyInstaller (if needed)..."
& $envPython -m pip install --quiet -r "$PSScriptRoot\requirements.txt"
& $envPython -m pip install --quiet "pyinstaller>=6.0"

Write-Host "Building (this takes a few minutes - faster-whisper's ctranslate2 backend is large)..."
Push-Location $PSScriptRoot
try {
    & $envPython -m PyInstaller personalai.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$exePath = "$PSScriptRoot\dist\Nexus\Nexus.exe"
if (!(Test-Path $exePath)) { throw "Build finished but $exePath is missing." }

if ($Shortcut) {
    Write-Host "Creating a Desktop shortcut..."
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut("$desktop\Nexus.lnk")
    $lnk.TargetPath = $exePath
    $lnk.WorkingDirectory = "$PSScriptRoot\dist\Nexus"
    $lnk.IconLocation = $exePath
    $lnk.Description = "Nexus - your local, offline AI assistant"
    $lnk.Save()
    Write-Host "  Shortcut created: $desktop\Nexus.lnk"
}

Write-Host ""
Write-Host "===== Done ====="
Write-Host "Run: $exePath"
Write-Host "(dist\ and build\ are large and disposable - do not commit them; they are gitignored.)"
