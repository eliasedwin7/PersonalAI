@echo off
rem Double-click to launch the PersonalAI desktop app - no PyInstaller
rem build needed, this just runs it through the conda env directly.
rem For a real standalone .exe (no conda involved at all), see
rem Build-PersonalAI-Exe.ps1.
set PYTHONIOENCODING=utf-8
conda run -n personalai --no-capture-output myai gui
