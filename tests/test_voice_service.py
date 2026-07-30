"""voice_service tests: sounddevice/faster_whisper/pyttsx3 are all
stubbed via sys.modules (no real microphone, model download, or SAPI5
speech needed) - this tests our own glue code (WAV encoding, model/
engine caching, the availability checks), not those libraries.
"""

from __future__ import annotations

import sys
import time
import types
import wave
from io import BytesIO
from typing import ClassVar

import pytest

from personalai.services import voice_service
from personalai.services.voice_service import VoiceUnavailable


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch):
    """Each test gets fresh model/engine caches - these are meant to
    persist across real calls in the running app, but must not leak
    fake objects between tests."""
    monkeypatch.setattr(voice_service, "_whisper_models", {})
    monkeypatch.setattr(voice_service, "_tts_engine", None)


def _make_missing(monkeypatch, name: str) -> None:
    """Simulate `name` not being installed - sys.modules[name] = None
    makes `import name` raise ImportError, same as if it were absent."""
    monkeypatch.setitem(sys.modules, name, None)


# ---- availability checks ----

def test_is_recording_available_false_when_sounddevice_missing(monkeypatch):
    _make_missing(monkeypatch, "sounddevice")
    assert voice_service.is_recording_available() is False


def test_is_recording_available_true_when_present(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", types.ModuleType("sounddevice"))
    assert voice_service.is_recording_available() is True


def test_is_transcription_available_false_when_missing(monkeypatch):
    _make_missing(monkeypatch, "faster_whisper")
    assert voice_service.is_transcription_available() is False


def test_is_speech_available_false_when_missing(monkeypatch):
    _make_missing(monkeypatch, "pyttsx3")
    assert voice_service.is_speech_available() is False


# ---- Recorder ----

class _FakeStream:
    instances: ClassVar[list[_FakeStream]] = []

    def __init__(self, samplerate, channels, dtype, callback):
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.callback = callback
        self.started = False
        self.closed = False
        _FakeStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


def _install_fake_sounddevice(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = _FakeStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    _FakeStream.instances.clear()
    return fake_sd


def test_recorder_start_stop_produces_valid_wav(monkeypatch):
    import numpy as np

    _install_fake_sounddevice(monkeypatch)
    recorder = voice_service.Recorder()
    recorder.start()

    stream = _FakeStream.instances[-1]
    assert stream.started is True
    # Simulate two chunks of audio arriving via the capture callback.
    stream.callback(np.zeros((100, 1), dtype="int16"), 100, None, None)
    stream.callback(np.ones((50, 1), dtype="int16"), 50, None, None)

    wav_bytes = recorder.stop()
    assert stream.closed is True

    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == voice_service.SAMPLE_RATE
        assert wf.getnframes() == 150


def test_recorder_stop_without_start_raises():
    recorder = voice_service.Recorder()
    with pytest.raises(VoiceUnavailable):
        recorder.stop()


def test_recorder_start_raises_when_sounddevice_missing(monkeypatch):
    _make_missing(monkeypatch, "sounddevice")
    recorder = voice_service.Recorder()
    with pytest.raises(VoiceUnavailable, match="sounddevice"):
        recorder.start()


# ---- silence detection (fixes the "always hallucinates 'you'" bug) ----

def test_recorder_heard_speech_false_when_only_silence(monkeypatch):
    import numpy as np

    _install_fake_sounddevice(monkeypatch)
    recorder = voice_service.Recorder()
    recorder.start()
    stream = _FakeStream.instances[-1]

    quiet = np.zeros((100, 1), dtype="int16")
    for _ in range(5):
        stream.callback(quiet, 100, None, None)

    assert recorder.heard_speech() is False


def test_recorder_heard_speech_true_when_loud_chunk_arrives(monkeypatch):
    import numpy as np

    _install_fake_sounddevice(monkeypatch)
    recorder = voice_service.Recorder()
    recorder.start()
    stream = _FakeStream.instances[-1]

    quiet = np.zeros((100, 1), dtype="int16")
    loud = np.full((100, 1), 5000, dtype="int16")
    stream.callback(quiet, 100, None, None)  # establishes a near-zero noise floor
    stream.callback(loud, 100, None, None)   # clearly above it

    assert recorder.heard_speech() is True


def test_recorder_should_auto_stop_false_before_start():
    recorder = voice_service.Recorder()
    assert recorder.should_auto_stop() is False


def test_recorder_should_auto_stop_after_trailing_silence(monkeypatch):
    import numpy as np

    _install_fake_sounddevice(monkeypatch)
    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    recorder = voice_service.Recorder()
    recorder.start()
    stream = _FakeStream.instances[-1]

    loud = np.full((100, 1), 5000, dtype="int16")
    quiet = np.zeros((100, 1), dtype="int16")

    stream.callback(loud, 100, None, None)
    assert recorder.should_auto_stop() is False

    fake_now[0] += 0.3
    stream.callback(quiet, 100, None, None)
    assert recorder.should_auto_stop() is False  # not quiet long enough yet

    fake_now[0] += voice_service.TRAILING_SILENCE_AUTO_STOP_S + 0.1
    stream.callback(quiet, 100, None, None)
    assert recorder.should_auto_stop() is True


def test_recorder_should_auto_stop_never_true_without_speech_first(monkeypatch):
    """Silence before anything was ever said must NOT trigger an
    auto-stop - only trailing silence AFTER speech should."""
    import numpy as np

    _install_fake_sounddevice(monkeypatch)
    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    recorder = voice_service.Recorder()
    recorder.start()
    stream = _FakeStream.instances[-1]
    quiet = np.zeros((100, 1), dtype="int16")
    stream.callback(quiet, 100, None, None)

    fake_now[0] += voice_service.TRAILING_SILENCE_AUTO_STOP_S + 5
    stream.callback(quiet, 100, None, None)
    assert recorder.should_auto_stop() is False


def test_recorder_should_auto_stop_hits_hard_cap_regardless_of_silence(monkeypatch):
    import numpy as np

    _install_fake_sounddevice(monkeypatch)
    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    recorder = voice_service.Recorder()
    recorder.start()
    stream = _FakeStream.instances[-1]
    loud = np.full((100, 1), 5000, dtype="int16")
    stream.callback(loud, 100, None, None)

    fake_now[0] += voice_service.MAX_RECORDING_S + 1
    assert recorder.should_auto_stop() is True


# ---- transcribe ----

class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeWhisperModel:
    created_with: ClassVar[list[tuple]] = []

    def __init__(self, model_size, device, compute_type):
        self.model_size = model_size
        _FakeWhisperModel.created_with.append((model_size, device, compute_type))

    last_vad_filter: ClassVar[bool | None] = None

    def transcribe(self, path, vad_filter=False):
        _FakeWhisperModel.last_vad_filter = vad_filter
        return [_FakeSegment(" hello "), _FakeSegment("world ")], {"language": "en"}


def _install_fake_faster_whisper(monkeypatch):
    fake_mod = types.ModuleType("faster_whisper")
    fake_mod.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_mod)
    _FakeWhisperModel.created_with.clear()
    _FakeWhisperModel.last_vad_filter = None
    return fake_mod


def test_transcribe_joins_segments_and_strips(monkeypatch):
    _install_fake_faster_whisper(monkeypatch)
    text = voice_service.transcribe(b"fake wav bytes", model_size="tiny.en")
    assert text == "hello world"


def test_transcribe_enables_vad_filter(monkeypatch):
    """vad_filter=True is the standard fix for Whisper models
    hallucinating text like "you" on silence/background noise."""
    _install_fake_faster_whisper(monkeypatch)
    voice_service.transcribe(b"fake wav bytes")
    assert _FakeWhisperModel.last_vad_filter is True


def test_transcribe_caches_model_per_size(monkeypatch):
    _install_fake_faster_whisper(monkeypatch)
    voice_service.transcribe(b"a", model_size="tiny.en")
    voice_service.transcribe(b"b", model_size="tiny.en")
    voice_service.transcribe(b"c", model_size="base.en")
    sizes_created = [size for size, _device, _ct in _FakeWhisperModel.created_with]
    assert sizes_created == ["tiny.en", "base.en"]  # tiny.en only built once


def test_transcribe_raises_when_faster_whisper_missing(monkeypatch):
    _make_missing(monkeypatch, "faster_whisper")
    with pytest.raises(VoiceUnavailable, match="faster-whisper"):
        voice_service.transcribe(b"fake wav bytes")


# ---- speak ----

class _FakeTtsEngine:
    instances: ClassVar[list[_FakeTtsEngine]] = []

    def __init__(self):
        self.said: list[str] = []
        self.ran = 0
        _FakeTtsEngine.instances.append(self)

    def say(self, text):
        self.said.append(text)

    def runAndWait(self):
        self.ran += 1


def _install_fake_pyttsx3(monkeypatch):
    fake_mod = types.ModuleType("pyttsx3")
    fake_mod.init = lambda: _FakeTtsEngine()
    monkeypatch.setitem(sys.modules, "pyttsx3", fake_mod)
    _FakeTtsEngine.instances.clear()
    return fake_mod


def test_speak_says_and_runs(monkeypatch):
    _install_fake_pyttsx3(monkeypatch)
    voice_service.speak("hello there")
    engine = _FakeTtsEngine.instances[-1]
    assert engine.said == ["hello there"]
    assert engine.ran == 1


def test_speak_reuses_engine_across_calls(monkeypatch):
    _install_fake_pyttsx3(monkeypatch)
    voice_service.speak("first")
    voice_service.speak("second")
    assert len(_FakeTtsEngine.instances) == 1


def test_speak_ignores_blank_text(monkeypatch):
    _install_fake_pyttsx3(monkeypatch)
    voice_service.speak("   ")
    assert _FakeTtsEngine.instances == []


def test_speak_raises_when_pyttsx3_missing(monkeypatch):
    _make_missing(monkeypatch, "pyttsx3")
    with pytest.raises(VoiceUnavailable, match="pyttsx3"):
        voice_service.speak("hello")
