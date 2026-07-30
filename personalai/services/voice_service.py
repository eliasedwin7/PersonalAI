"""Voice input/output for the desktop GUI: push-to-talk recording +
local transcription (faster-whisper) and reading replies aloud
(pyttsx3, offline via Windows SAPI5).

Both directions are optional, lazily-imported dependencies - `myai
chat`/`story`/`code` never pay their import cost, and a GUI running
without them installed just hides/disables the mic button and the
"read aloud" checkbox instead of crashing (see is_recording_available()/
is_transcription_available()/is_speech_available()).

Nothing here talks to the network or any LLM backend - this module only
turns speech into text and text into speech. faster-whisper runs
entirely on CPU (compute_type="int8"), matching this project's
no-GPU-required stance; its first use downloads a small model
(~75-150MB depending on size) from Hugging Face and caches it under
~/.cache/huggingface, after which transcription is fully offline.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import wave
from typing import TYPE_CHECKING

from personalai.core.errors import PersonalAIError

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # what whisper models expect
WHISPER_MODEL_SIZES = ("tiny.en", "base.en", "small.en")


class VoiceUnavailable(PersonalAIError):
    """Recording, transcription, or speech isn't available - the
    optional sounddevice/faster-whisper/pyttsx3 packages aren't
    installed, or no working microphone/audio output was found."""


def is_recording_available() -> bool:
    try:
        import sounddevice  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def is_transcription_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def is_speech_available() -> bool:
    try:
        import pyttsx3  # noqa: F401
    except ImportError:
        return False
    return True


class Recorder:
    """Push-to-talk recorder: start() begins capturing from the default
    microphone, stop() ends capture and returns the audio as WAV bytes.
    One Recorder instance is good for one recording - build a new one for
    the next.
    """

    def __init__(self) -> None:
        self._frames: list = []
        self._stream = None

    def start(self) -> None:
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise VoiceUnavailable(
                "Voice recording needs the 'sounddevice' package (and a "
                "working microphone): pip install sounddevice"
            ) from exc

        self._frames = []

        def _callback(indata, _frames, _time_info, _status) -> None:
            self._frames.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=_callback
        )
        self._stream.start()

    def stop(self) -> bytes:
        """Stop capturing and return the recording as 16kHz mono WAV
        bytes. Safe to call even if nothing was actually said - returns
        a (silent) empty-length WAV rather than raising."""
        if self._stream is None:
            raise VoiceUnavailable("Recording was never started.")
        self._stream.stop()
        self._stream.close()
        self._stream = None

        import numpy as np

        audio = (
            np.concatenate(self._frames, axis=0).flatten()
            if self._frames
            else np.zeros((0,), dtype="int16")
        )

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return buf.getvalue()


# Loading a whisper model takes a couple of seconds - cache one instance
# per model size for the lifetime of the process instead of reloading it
# on every recording.
_whisper_models: dict[str, WhisperModel] = {}


def transcribe(wav_bytes: bytes, model_size: str = "base.en") -> str:
    """Transcribe recorded audio to text using a local faster-whisper
    model. Runs synchronously and can take a few seconds (longer on
    first use of a given model_size, while it downloads) - callers
    running this from a GUI should submit it to a background task."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise VoiceUnavailable(
            "Transcription needs the 'faster-whisper' package: "
            "pip install faster-whisper"
        ) from exc

    model = _whisper_models.get(model_size)
    if model is None:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        _whisper_models[model_size] = model

    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(wav_bytes)
        segments, _info = model.transcribe(tmp_path)
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        os.unlink(tmp_path)


# pyttsx3's SAPI5 backend on Windows is meant to be driven by one
# long-lived engine instance (re-init()ing per call leaks COM state) -
# cache it the same way as the whisper models above.
_tts_engine = None


def speak(text: str) -> None:
    """Read text aloud via the system's TTS voice. Blocks until speech
    finishes - callers running this from a GUI should submit it to a
    background task so the window doesn't freeze while it talks."""
    text = text.strip()
    if not text:
        return
    try:
        import pyttsx3
    except ImportError as exc:
        raise VoiceUnavailable(
            "Reading replies aloud needs the 'pyttsx3' package: pip install pyttsx3"
        ) from exc

    global _tts_engine
    if _tts_engine is None:
        _tts_engine = pyttsx3.init()
    _tts_engine.say(text)
    _tts_engine.runAndWait()
