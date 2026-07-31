from __future__ import annotations

from personalai.services.setup_service import HardwareSnapshot, recommend_profile, setup_summary


def test_recommend_profile_prefers_16gb_gpu_when_detected():
    snapshot = HardwareSnapshot("Windows", 16, 32, 16, True)

    assert recommend_profile(snapshot) == "16gb"


def test_recommend_profile_uses_laptop_for_unknown_gpu():
    snapshot = HardwareSnapshot("Windows", 8, 16, None, False)

    assert recommend_profile(snapshot) == "laptop"
    assert "Ollama not found" in setup_summary(snapshot)[-1]
