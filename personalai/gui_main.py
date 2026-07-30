"""Dedicated GUI-only entry point, used by the frozen PyInstaller build
(see personalai.spec) and by Run-PersonalAI-GUI.bat.

Deliberately NOT personalai/__main__.py (which goes through cli.main()'s
argparse and requires a subcommand like `gui`) - a double-clicked .exe
has no arguments to parse, so it needs a bare entry point that jumps
straight to the window.
"""
from __future__ import annotations

from personalai.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
