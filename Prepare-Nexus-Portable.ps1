param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bundle = Join-Path $Root "dist\Nexus"

if (-not $SkipBuild) {
    & (Join-Path $Root "Build-PersonalAI-Exe.ps1")
}

if (-not (Test-Path $Bundle)) {
    throw "Bundle folder was not found: $Bundle"
}

$Readme = @"
Nexus portable bundle
=====================

1. Install Ollama once on this PC:
   https://ollama.com

2. Start Nexus.exe.

3. In Nexus, open System and choose the hardware profile.
   For a 32 GB RAM / 16 GB VRAM PC shared with Forge or ComfyUI, use:
   16 GB GPU shared with Forge / ComfyUI

4. Install the recommended Ollama models from System or run:
   ollama pull qwen3:4b
   ollama pull qwen3:8b
   ollama pull qwen3:14b
   ollama pull gemma3:4b
   ollama pull embeddinggemma

5. Keep "Release GPU memory after each reply" enabled when Forge or ComfyUI
   is running on the same GPU.

Conversations and memory live in:
%USERPROFILE%\.personalai
"@

Set-Content -Path (Join-Path $Bundle "NEXUS_PORTABLE_README.txt") -Value $Readme -Encoding UTF8
Write-Host "Portable Nexus bundle is ready:"
Write-Host $Bundle
