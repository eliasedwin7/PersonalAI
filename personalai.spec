# PyInstaller spec for Nexus's desktop GUI (one-folder, windowed).
#
# Build with:  Build-PersonalAI-Exe.ps1   (or: pyinstaller personalai.spec)
#
# Produces dist/Nexus/Nexus.exe - a real double-clickable app,
# no conda/terminal needed to launch it (though the terminal `myai` command
# still works the same as always for one-shot/automated use).
#
# Freezes in the voice extras (sounddevice/faster-whisper/pyttsx3) too, not
# just the base GUI - their native bits (portaudio's DLL, ctranslate2's
# compiled libs) don't get picked up by PyInstaller's static analysis, so
# they're collected explicitly below. If a frozen build's mic button or
# TTS checkbox misbehaves but `myai gui` from the conda env works fine,
# that's the first place to look - not a bug in voice_service.py itself.

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

datas = [
    ("personalai/ui/icon.ico", "personalai/ui"),
]
datas += collect_data_files("sounddevice")     # bundled portaudio DLL
datas += collect_data_files("faster_whisper")  # tokenizer/asset files
datas += collect_data_files("ctranslate2")     # faster-whisper's inference backend

binaries = collect_dynamic_libs("ctranslate2")

a = Analysis(
    ["personalai/gui_main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "sounddevice",
        "faster_whisper",
        "ctranslate2",
        "pyttsx3",
        "pyttsx3.drivers",
        "pyttsx3.drivers.sapi5",  # Windows TTS backend
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Nexus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,      # windowed
    icon="personalai/ui/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Nexus",
)
