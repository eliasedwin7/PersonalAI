"""Version/build metadata shown in Nexus System."""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

PACKAGE_VERSION = "0.1.0"
BUILD_INFO_FILE = Path(__file__).resolve().parent.parent / "build_info.json"


def app_version() -> str:
    try:
        return metadata.version("personalai")
    except metadata.PackageNotFoundError:
        return PACKAGE_VERSION


def build_date() -> str:
    try:
        raw = json.loads(BUILD_INFO_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "development"
    return str(raw.get("build_date") or "development")
