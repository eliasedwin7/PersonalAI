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
import time
import wave
from typing import TYPE_CHECKING

from personalai.core.errors import PersonalAIError

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # what whisper models expect
WHISPER_MODEL_SIZES = ("tiny.en", "base.en", "small.en")

# Silence/auto-stop tuning for Recorder.should_auto_stop() - the goal is
# "stop listening on its own once you've said something and gone quiet",
# without a fixed volume threshold that would be wrong for every mic's
# gain/sensitivity. So instead of a hardcoded loudness cutoff, the
# recorder tracks a slowly-adapting noise floor and calls anything a
# fixed margin above IT "speech" - see Recorder._on_chunk.
SILENCE_RMS_MULTIPLIER = 3.0   # "speech" = at least this many times the noise floor...
SILENCE_RMS_FLOOR = 60.0       # ...plus this flat minimum, for near-silent noise floors
TRAILING_SILENCE_AUTO_STOP_S = 1.1  # how long you have to go quiet before it auto-stops
MAX_RECORDING_S = 30.0         # hard cap regardless of silence detection


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
    """Recorder: start() begins capturing from the default microphone,
    stop() ends capture and returns the audio as WAV bytes. One Recorder
    instance is good for one recording - build a new one for the next.

    Also tracks whether it heard actual speech (heard_speech()) and
    whether enough trailing silence has passed that the caller should
    stop on its own (should_auto_stop()) - see the module-level
    SILENCE_*/TRAILING_SILENCE_*/MAX_RECORDING_S constants. Both exist
    to fix the same underlying problem: faster-whisper (like most
    Whisper models) hallucinates text like "you" or "Thank you." when
    fed silence, so the fix is to never hand it silence in the first
    place - detect "no one actually spoke" ourselves and skip
    transcription entirely, and detect "they stopped talking" so the UI
    doesn't need a second manual tap to end the recording.
    """

    def __init__(self) -> None:
        self._frames: list = []
        self._stream = None
        self._noise_floor: float = 0.0
        self._heard_speech = False
        self._silence_started_at: float | None = None
        self._started_at: float = 0.0

    def start(self) -> None:
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise VoiceUnavailable(
                "Voice recording needs the 'sounddevice' package (and a "
                "working microphone): pip install sounddevice"
            ) from exc

        self._frames = []
        # Start assuming silence (0.0), NOT the first chunk's own RMS - if
        # someone starts talking immediately, that first chunk WOULD BE the
        # loud one, and calibrating "ambient noise" to a loud sample means
        # nothing ever reads as louder than "ambient" again. SILENCE_RMS_FLOOR
        # is the real floor until quiet chunks actually arrive to adapt it.
        self._noise_floor = 0.0
        self._heard_speech = False
        self._silence_started_at = None
        self._started_at = time.monotonic()

        def _callback(indata, _frames, _time_info, _status) -> None:
            self._frames.append(indata.copy())
            self._on_chunk(indata)

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=_callback
        )
        self._stream.start()

    def _on_chunk(self, chunk) -> None:
        """Runs on sounddevice's audio thread for every captured chunk -
        keep this cheap and lock-free (plain attribute writes only)."""
        import numpy as np

        rms = float(np.sqrt(np.mean(chunk.astype("float64") ** 2)))
        now = time.monotonic()

        speech_threshold = self._noise_floor * SILENCE_RMS_MULTIPLIER + SILENCE_RMS_FLOOR
        if rms >= speech_threshold:
            self._heard_speech = True
            self._silence_started_at = None
        else:
            # Only let quiet stretches drag the floor down/adapt it -
            # loud speech must never get averaged into "ambient noise".
            self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms
            if self._heard_speech and self._silence_started_at is None:
                self._silence_started_at = now

    def heard_speech(self) -> bool:
        """Whether any audio clearly above the ambient noise floor was
        captured during this recording - False means "stayed silent the
        whole time", the signal to skip transcription entirely rather
        than hand faster-whisper nothing and get a hallucinated reply."""
        return self._heard_speech

    def should_auto_stop(self) -> bool:
        """Call periodically (e.g. from a GUI-thread timer) while
        recording - True once trailing silence (or the hard time cap)
        means it's time to stop on its own, no manual tap needed."""
        if self._stream is None:
            return False
        now = time.monotonic()
        if now - self._started_at >= MAX_RECORDING_S:
            return True
        if self._silence_started_at is not None:
            return now - self._silence_started_at >= TRAILING_SILENCE_AUTO_STOP_S
        return False

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
    running this from a GUI should submit it to a background task.

    vad_filter=True (faster-whisper's bundled Silero voice-activity
    detector) trims/ignores non-speech stretches before they ever reach
    the model - the standard fix for Whisper models hallucinating text
    like "you" or "Thank you." on silence or background noise. This is
    a second layer of defense; Recorder.heard_speech() (see above) is
    the first, meant to skip calling this function at all when nothing
    was said."""
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
        segments, _info = model.transcribe(tmp_path, vad_filter=True)
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
