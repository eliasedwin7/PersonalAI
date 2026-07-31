"""Hardware/setup recommendations for a low-friction Nexus first run."""

from __future__ import annotations

import ctypes
import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareSnapshot:
    os_name: str
    cpu_count: int
    ram_gb: int | None
    gpu_vram_gb: int | None
    ollama_found: bool


def detect_hardware() -> HardwareSnapshot:
    """Best-effort local detection; every field is allowed to be unknown."""
    return HardwareSnapshot(
        os_name=f"{platform.system()} {platform.release()}".strip(),
        cpu_count=max(1, __import__("os").cpu_count() or 1),
        ram_gb=_detect_ram_gb(),
        gpu_vram_gb=_detect_nvidia_vram_gb(),
        ollama_found=shutil.which("ollama") is not None,
    )


def recommend_profile(snapshot: HardwareSnapshot) -> str:
    """Pick the safest bundled Ollama profile from what the machine appears to have."""
    if snapshot.gpu_vram_gb is not None:
        if snapshot.gpu_vram_gb >= 14:
            return "16gb"
        if snapshot.gpu_vram_gb >= 7:
            return "8gb"
    if snapshot.ram_gb is not None and snapshot.ram_gb >= 30:
        return "8gb"
    return "laptop"


def setup_summary(snapshot: HardwareSnapshot) -> list[str]:
    ram = "unknown RAM" if snapshot.ram_gb is None else f"{snapshot.ram_gb} GB RAM"
    vram = "unknown VRAM" if snapshot.gpu_vram_gb is None else f"{snapshot.gpu_vram_gb} GB VRAM"
    ollama = "Ollama found" if snapshot.ollama_found else "Ollama not found on PATH"
    return [snapshot.os_name, f"{snapshot.cpu_count} CPU threads", ram, vram, ollama]


def _detect_ram_gb() -> int | None:
    if platform.system().lower() != "windows":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return None
    if not ok:
        return None
    return round(status.ullTotalPhys / (1024**3))


def _detect_nvidia_vram_gb() -> int | None:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        result = subprocess.run(
            [nvidia_smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    values = []
    for line in result.stdout.splitlines():
        try:
            values.append(int(line.strip()))
        except ValueError:
            continue
    if not values:
        return None
    return round(max(values) / 1024)
