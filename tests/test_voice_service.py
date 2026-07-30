"""voice_service tests: sounddevice/faster_whisper/pyttsx3 are all
stubbed via sys.modules (no real microphone, model download, or SAPI5
speech needed) - this tests our own glue code (WAV encoding, model/
engine caching, the availability checks), not those libraries.
"""

from __future__ import annotations

import queue
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
#
# Recorder captures via sounddevice's callback-based InputStream - the
# straightforward, standard approach. (An earlier version of this
# module briefly switched to a background thread repeatedly calling
# blocking sd.rec()/sd.wait(), after finding one specific WDM-KS
# microphone endpoint whose InputStream callback never fired at all on
# one piece of test hardware - but repeatedly reopening a stream turned
# out to permanently wedge that same device at the OS/driver level,
# which is worse. InputStream's callback mode is reliable for the
# ordinary MME/DirectSound/WASAPI devices most people actually have, so
# that's what this uses; a WDM-KS endpoint that won't cooperate is a
# reason to pick a different device (see list_input_devices_detailed()
# and `myai mic-test --device N`), not a reason to make every other
# device's recording less robust.)

class _FakeStream:
    instances: ClassVar[list[_FakeStream]] = []

    def __init__(self, samplerate, channels, dtype, callback, device=None):
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.callback = callback
        self.device = device
        self.started = False
        self.closed = False
        _FakeStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc_info):
        self.stop()
        self.close()
        return False


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


def test_recorder_passes_configured_device_to_input_stream(monkeypatch):
    """A specific device index must reach sounddevice - the whole point
    of Config.mic_device is overriding a broken/wrong OS default (a real
    issue observed on hardware this was built against: the "default"
    endpoint silently returned all-zero audio)."""
    _install_fake_sounddevice(monkeypatch)
    recorder = voice_service.Recorder(device=7)
    recorder.start()
    assert _FakeStream.instances[-1].device == 7


def test_recorder_default_device_is_none(monkeypatch):
    _install_fake_sounddevice(monkeypatch)
    recorder = voice_service.Recorder()
    recorder.start()
    assert _FakeStream.instances[-1].device is None


def test_recorder_surfaces_portaudio_start_error_as_user_facing(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")

    class FakePortAudioError(Exception):
        pass

    class BrokenStream:
        def __init__(self, *args, **kwargs):
            raise FakePortAudioError("device unavailable")

    fake_sd.PortAudioError = FakePortAudioError
    fake_sd.InputStream = BrokenStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    with pytest.raises(VoiceUnavailable, match="Could not open"):
        voice_service.Recorder(device=9).start()


# ---- silence detection (fixes the "always hallucinates 'you'" bug) ----
#
# _on_chunk() is the pure logic behind heard_speech()/should_auto_stop()/
# peak_rms() - these tests call it directly rather than going through a
# real InputStream callback, since the math doesn't care how a chunk
# arrived. should_auto_stop()'s tests set _stream/_started_at directly
# for the same reason (bypassing start(), which would need a real/fake
# sounddevice module these tests don't otherwise need).

def test_recorder_heard_speech_false_when_only_silence():
    import numpy as np

    recorder = voice_service.Recorder()
    quiet = np.zeros((100, 1), dtype="int16")
    for _ in range(5):
        recorder._on_chunk(quiet)

    assert recorder.heard_speech() is False


def test_recorder_heard_speech_true_when_loud_chunk_arrives():
    import numpy as np

    recorder = voice_service.Recorder()
    quiet = np.zeros((100, 1), dtype="int16")
    loud = np.full((100, 1), 5000, dtype="int16")
    recorder._on_chunk(quiet)  # establishes a near-zero noise floor
    recorder._on_chunk(loud)  # clearly above it

    assert recorder.heard_speech() is True


def test_recorder_should_auto_stop_false_before_start():
    recorder = voice_service.Recorder()
    assert recorder.should_auto_stop() is False


def test_recorder_should_auto_stop_after_trailing_silence(monkeypatch):
    import numpy as np

    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    recorder = voice_service.Recorder()
    recorder._stream = object()  # any truthy sentinel - only identity/None-ness matters
    recorder._started_at = fake_now[0]

    loud = np.full((100, 1), 5000, dtype="int16")
    quiet = np.zeros((100, 1), dtype="int16")

    recorder._on_chunk(loud)
    assert recorder.should_auto_stop() is False

    fake_now[0] += 0.3
    recorder._on_chunk(quiet)
    assert recorder.should_auto_stop() is False  # not quiet long enough yet

    fake_now[0] += voice_service.TRAILING_SILENCE_AUTO_STOP_S + 0.1
    recorder._on_chunk(quiet)
    assert recorder.should_auto_stop() is True


def test_recorder_should_auto_stop_never_true_without_speech_first(monkeypatch):
    """Silence before anything was ever said must NOT trigger an
    auto-stop - only trailing silence AFTER speech should."""
    import numpy as np

    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    recorder = voice_service.Recorder()
    recorder._stream = object()  # any truthy sentinel - only identity/None-ness matters
    recorder._started_at = fake_now[0]
    quiet = np.zeros((100, 1), dtype="int16")
    recorder._on_chunk(quiet)

    fake_now[0] += voice_service.TRAILING_SILENCE_AUTO_STOP_S + 5
    recorder._on_chunk(quiet)
    assert recorder.should_auto_stop() is False


def test_recorder_should_auto_stop_hits_hard_cap_regardless_of_silence(monkeypatch):
    import numpy as np

    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    recorder = voice_service.Recorder()
    recorder._stream = object()  # any truthy sentinel - only identity/None-ness matters
    recorder._started_at = fake_now[0]
    loud = np.full((100, 1), 5000, dtype="int16")
    recorder._on_chunk(loud)

    fake_now[0] += voice_service.MAX_RECORDING_S + 1
    assert recorder.should_auto_stop() is True


def test_recorder_peak_rms_tracks_loudest_chunk():
    import numpy as np

    recorder = voice_service.Recorder()
    recorder._on_chunk(np.full((100, 1), 40, dtype="int16"))
    recorder._on_chunk(np.full((100, 1), 5000, dtype="int16"))
    recorder._on_chunk(np.full((100, 1), 200, dtype="int16"))

    assert recorder.peak_rms() == pytest.approx(5000.0)


def test_recorder_peak_rms_zero_before_any_audio():
    assert voice_service.Recorder().peak_rms() == 0.0


# ---- mic diagnostics (list_input_devices / mic_level_test) ----

def test_list_input_devices_empty_when_sounddevice_missing(monkeypatch):
    _make_missing(monkeypatch, "sounddevice")
    assert voice_service.list_input_devices() == []


def _install_fake_devices(monkeypatch, default_index=2):
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "Built-in Mic", "max_input_channels": 1},
        {"name": "USB Headset Mic", "max_input_channels": 1},
    ]

    class _Default:
        device = (default_index, 0)

    fake_sd.default = _Default()
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)


def test_list_input_devices_filters_output_only_and_marks_default(monkeypatch):
    _install_fake_devices(monkeypatch)
    assert voice_service.list_input_devices() == [
        "[1] Built-in Mic",
        "[2] USB Headset Mic (default)",
    ]


def test_list_input_devices_detailed_returns_structured_tuples(monkeypatch):
    _install_fake_devices(monkeypatch)
    assert voice_service.list_input_devices_detailed() == [
        (1, "Built-in Mic", False),
        (2, "USB Headset Mic", True),
    ]


def test_list_input_devices_detailed_empty_when_sounddevice_missing(monkeypatch):
    _make_missing(monkeypatch, "sounddevice")
    assert voice_service.list_input_devices_detailed() == []


# mic_level_test() is a one-shot diagnostic (a single sd.rec()/sd.wait()
# call, not a loop), so unlike Recorder it doesn't need InputStream's
# callback mode at all - this fake just returns whatever's queued.

class _FakeSoundDeviceRec:
    def __init__(self):
        self.calls: list[dict] = []
        self._queue: queue.Queue = queue.Queue()

    def push_chunk(self, chunk) -> None:
        self._queue.put(chunk)

    def rec(self, frames, samplerate, channels, dtype, device=None):
        self.calls.append({"frames": frames, "samplerate": samplerate,
                           "channels": channels, "dtype": dtype, "device": device})
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            import numpy as np
            return np.zeros((frames, channels), dtype=dtype)

    def wait(self) -> None:
        pass


def _install_fake_sd_rec(monkeypatch) -> _FakeSoundDeviceRec:
    fake = _FakeSoundDeviceRec()
    fake_mod = types.ModuleType("sounddevice")
    fake_mod.rec = fake.rec
    fake_mod.wait = fake.wait
    monkeypatch.setitem(sys.modules, "sounddevice", fake_mod)
    return fake


def test_mic_level_test_raises_when_sounddevice_missing(monkeypatch):
    _make_missing(monkeypatch, "sounddevice")
    with pytest.raises(VoiceUnavailable, match="sounddevice"):
        voice_service.mic_level_test(seconds=1.0)


def test_mic_level_test_passes_device_through(monkeypatch):
    import numpy as np

    fake = _install_fake_sd_rec(monkeypatch)
    total_frames = int(voice_service.SAMPLE_RATE * 1.0)
    fake.push_chunk(np.zeros((total_frames, 1), dtype="int16"))

    voice_service.mic_level_test(seconds=1.0, device=3)
    assert fake.calls[-1]["device"] == 3


def test_mic_level_test_reports_peak_and_windowed_levels(monkeypatch):
    import numpy as np

    fake = _install_fake_sd_rec(monkeypatch)
    total_frames = int(voice_service.SAMPLE_RATE * 1.0)
    fake.push_chunk(np.full((total_frames, 1), 1000, dtype="int16"))

    peak, levels = voice_service.mic_level_test(seconds=1.0)
    assert peak == pytest.approx(1000.0, rel=0.01)
    assert len(levels) >= 1


def test_mic_level_test_returns_zero_peak_when_silent(monkeypatch):
    """A real mic capture is always full-length (silence still comes
    back as an array of near-zero samples, never an empty one) -
    genuinely nothing captured only happens for a 0-length request."""
    import numpy as np

    fake = _install_fake_sd_rec(monkeypatch)
    total_frames = int(voice_service.SAMPLE_RATE * 1.0)
    fake.push_chunk(np.zeros((total_frames, 1), dtype="int16"))

    peak, levels = voice_service.mic_level_test(seconds=1.0)
    assert peak == 0.0
    assert len(levels) >= 1
    assert all(level == 0.0 for level in levels)


def test_mic_level_test_empty_for_zero_length_request(monkeypatch):
    import numpy as np

    fake = _install_fake_sd_rec(monkeypatch)
    fake.push_chunk(np.zeros((0, 1), dtype="int16"))

    peak, levels = voice_service.mic_level_test(seconds=0.0)
    assert peak == 0.0
    assert levels == []


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
