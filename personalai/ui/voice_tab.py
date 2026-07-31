"""Voice tab: a dedicated "talk to it" assistant, separate from the
Chat tab (which stays plain typing - see ChatTab's module docstring).

Tap the orb to start talking, tap again to stop - it transcribes
locally (faster-whisper), sends your words to the same ChatService the
other tabs use, streams the reply into the log, and speaks it back
(pyttsx3) before returning to idle, ready for the next turn. The orb's
color/pulse animates through idle -> listening -> thinking -> speaking
so it reads as "alive" rather than a frozen button.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from personalai.core.conversation import Conversation
from personalai.core.errors import PersonalAIError
from personalai.services import voice_service
from personalai.services.chat_service import ChatService
from personalai.services.command_service import parse_app_command
from personalai.ui import transcript_view
from personalai.ui.workers import TaskRunner

VOICE_SESSION = "voice"
VOICE_TASK = "general"  # same system prompt as the Chat tab's General mode

ORB_SIZE = 220
STATE_COLORS = {
    "idle": QColor("#3a6df0"),
    "listening": QColor("#e0455c"),
    "transcribing": QColor("#c77bf0"),
    "thinking": QColor("#c77bf0"),
    "speaking": QColor("#3ad18a"),
}
STATE_SPEEDS = {
    "idle": 0.035,
    "listening": 0.18,
    "transcribing": 0.12,
    "thinking": 0.12,
    "speaking": 0.22,
}
STATE_LABELS = {
    "idle": "Tap to talk",
    "listening": "Listening… (stops on its own when you pause)",
    "transcribing": "Transcribing…",
    "thinking": "Thinking…",
    "speaking": "Speaking…",
}
SILENCE_POLL_MS = 150
INPUT_LEVEL_FULL_SCALE = 1_200.0


class VoiceOrb(QWidget):
    """A pulsing, glowing circle whose color and pulse speed reflect
    the current state. Click it to advance the conversation."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(ORB_SIZE, ORB_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._state = "idle"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)  # ~25fps, cheap enough to always run

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def _tick(self) -> None:
        self._phase += STATE_SPEEDS.get(self._state, STATE_SPEEDS["idle"])
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event) -> None:
        base_color = STATE_COLORS.get(self._state, STATE_COLORS["idle"])
        pulse = (math.sin(self._phase) + 1) / 2  # 0..1
        min_radius, max_radius = ORB_SIZE * 0.27, ORB_SIZE * 0.42
        radius = min_radius + pulse * (max_radius - min_radius)
        center = QPointF(self.width() / 2, self.height() / 2)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        glow_radius = radius * 1.7
        glow = QRadialGradient(center, glow_radius)
        inner = QColor(base_color)
        inner.setAlpha(70)
        outer = QColor(base_color)
        outer.setAlpha(0)
        glow.setColorAt(0.0, inner)
        glow.setColorAt(1.0, outer)
        painter.setBrush(glow)
        painter.drawEllipse(center, glow_radius, glow_radius)

        painter.setBrush(base_color)
        painter.drawEllipse(center, radius, radius)
        painter.end()


class VoiceTab(QWidget):
    command_requested = Signal(object)

    def __init__(self, chat_service: ChatService, task_runner: TaskRunner,
                config_store=None) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.config_store = config_store
        self.conversation: Conversation = chat_service.store.load_or_create(
            VOICE_SESSION, VOICE_TASK
        )
        self._state = "idle"
        self._recorder: voice_service.Recorder | None = None
        self._silence_timer = QTimer(self)
        self._silence_timer.setInterval(SILENCE_POLL_MS)
        self._silence_timer.timeout.connect(self._check_auto_stop)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("Voice conversation")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("Microphone: System default"))
        device_row.addStretch(1)
        self.test_mic_btn = QPushButton("Test microphone")
        self.test_mic_btn.setToolTip("Records a short sample and shows whether this device receives sound.")
        self.test_mic_btn.clicked.connect(self._test_microphone)
        device_row.addWidget(self.test_mic_btn)
        layout.addLayout(device_row)

        level_row = QHBoxLayout()
        self.level_label = QLabel("Input level")
        level_row.addWidget(self.level_label)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setTextVisible(False)
        self.level_bar.setToolTip("Live microphone input level while listening.")
        level_row.addWidget(self.level_bar, stretch=1)
        layout.addLayout(level_row)

        layout.addStretch(1)

        orb_row = QHBoxLayout()
        orb_row.addStretch(1)
        self.orb = VoiceOrb()
        self.orb.clicked.connect(self._on_orb_clicked)
        orb_row.addWidget(self.orb)
        orb_row.addStretch(1)
        layout.addLayout(orb_row)

        self.status_label = QLabel(STATE_LABELS["idle"])
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 15px; color: #c8c8c8;")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        options_row = QHBoxLayout()
        self.speak_check = QCheckBox("Speak replies aloud")
        self.speak_check.setChecked(chat_service.config.read_replies_aloud)
        if voice_service.is_speech_available():
            self.speak_check.toggled.connect(self._on_speak_toggled)
        else:
            self.speak_check.setEnabled(False)
            self.speak_check.setToolTip("Needs the 'pyttsx3' package: pip install pyttsx3")
        options_row.addStretch(1)
        options_row.addWidget(self.speak_check)
        layout.addLayout(options_row)

        layout.addWidget(QLabel("Conversation"))
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        layout.addWidget(self.transcript, stretch=1)

        if not (voice_service.is_recording_available()
                and voice_service.is_transcription_available()):
            self.orb.setEnabled(False)
            self.status_label.setText("Needs the 'sounddevice' and 'faster-whisper' packages")
            self.test_mic_btn.setEnabled(False)

        transcript_view.render_transcript(self.transcript, self.conversation)

    # ---- state machine ----

    def _set_state(self, state: str) -> None:
        self._state = state
        self.orb.set_state(state)
        self.status_label.setText(STATE_LABELS[state])

    def _on_orb_clicked(self) -> None:
        if not self.orb.isEnabled():
            return
        if self._state == "idle":
            self._start_listening()
        elif self._state == "listening":
            self._stop_listening()
        # ignore clicks while transcribing/thinking/speaking - one turn at a time

    def _start_listening(self) -> None:
        self._recorder = voice_service.Recorder()
        try:
            self._recorder.start()
        except PersonalAIError as exc:
            self._recorder = None
            QMessageBox.warning(self, "Voice", str(exc))
            return
        self._set_state("listening")
        self.test_mic_btn.setEnabled(False)
        self._silence_timer.start()

    def _check_auto_stop(self) -> None:
        """Polled from the GUI thread (not the audio callback thread,
        which can't safely touch Qt) - stop on its own once the
        Recorder reports enough trailing silence, no manual tap needed."""
        if self._recorder is None:
            return
        self._update_live_level()
        if self._recorder.should_auto_stop():
            self._stop_listening()

    def _stop_listening(self) -> None:
        self._silence_timer.stop()
        recorder, self._recorder = self._recorder, None
        if recorder is None:
            return
        self.test_mic_btn.setEnabled(True)
        self.level_bar.setValue(0)
        try:
            wav_bytes = recorder.stop()
        except PersonalAIError as exc:
            self._on_error(exc)
            return

        if not recorder.heard_speech():
            # Never hand faster-whisper pure silence - that's exactly what
            # makes Whisper models hallucinate text like "you" or "Thank
            # you." - so just go back to idle instead of transcribing.
            # The peak level is shown so "it's not hearing me" (mic/OS
            # input problem - peak stays near 0) can be told apart from
            # "it heard something but not clearly enough" (peak is
            # nonzero but this module's sensitivity needs adjusting).
            peak = recorder.peak_rms()
            hint = " - check your system microphone settings" if peak < 5 else ""
            self.status_label.setText(
                f"Didn't hear anything (peak input level: {peak:.0f}){hint} - "
                "tap to try again"
            )
            self._state = "idle"
            self.orb.set_state("idle")
            return

        self._set_state("transcribing")
        model_size = self.chat_service.config.whisper_model
        self.task_runner.submit(
            voice_service.transcribe, wav_bytes, model_size,
            on_result=self._on_transcribed,
            on_error=self._on_error,
        )

    def _on_transcribed(self, text: str) -> None:
        text = text.strip()
        if not text:
            self._set_state("idle")
            return
        command = parse_app_command(
            text,
            self.chat_service.config.voice_wake_word,
            self.chat_service.config.voice_commands_enabled,
        )
        if command is not None:
            transcript_view.append_role_label(self.transcript, "user")
            transcript_view.append_body(self.transcript, text + "\n\n")
            transcript_view.append_role_label(self.transcript, "assistant")
            transcript_view.append_body(self.transcript, command.response + "\n\n")
            self.command_requested.emit(command)
            self._set_state("idle")
            return
        transcript_view.append_role_label(self.transcript, "user")
        transcript_view.append_body(self.transcript, text + "\n\n")
        transcript_view.append_role_label(self.transcript, "assistant")
        self._set_state("thinking")
        self.task_runner.submit(
            self.chat_service.send, self.conversation, text,
            on_progress=lambda token: transcript_view.append_body(self.transcript, token),
            on_result=self._on_reply,
            on_error=self._on_error,
        )

    def _on_reply(self, reply: str) -> None:
        # Re-render from the now-saved conversation instead of just
        # appending "\n\n" - swaps the raw streamed text for a markdown-
        # rendered reply (code blocks, bold, lists, ...) now that the
        # full message is known.
        transcript_view.render_transcript(self.transcript, self.conversation)
        if self.speak_check.isChecked() and voice_service.is_speech_available():
            self._set_state("speaking")
            self.task_runner.submit(
                voice_service.speak, reply,
                on_result=lambda _r=None: self._set_state("idle"),
                on_error=self._on_error,
            )
        else:
            self._set_state("idle")

    def _on_error(self, exc: BaseException) -> None:
        self._set_state("idle")
        self.test_mic_btn.setEnabled(self.orb.isEnabled())
        QMessageBox.warning(self, "Voice", str(exc))

    # ---- microphone diagnostics ----

    def _test_microphone(self) -> None:
        if self._state != "idle":
            return
        self.test_mic_btn.setEnabled(False)
        self.status_label.setText("Testing microphone - speak normally...")
        self.task_runner.submit(
            voice_service.mic_level_test, 3.0,
            on_result=self._on_microphone_tested,
            on_error=self._on_microphone_test_error,
        )

    def _on_microphone_tested(self, result: tuple[float, list[float]]) -> None:
        peak, _levels = result
        self.test_mic_btn.setEnabled(self.orb.isEnabled())
        self._set_level(peak)
        if peak < 80:
            self.status_label.setText(
                "No usable microphone signal. Check the system default input and test again."
            )
        else:
            self.status_label.setText(f"Microphone is receiving sound (peak level: {peak:.0f}).")

    def _on_microphone_test_error(self, exc: BaseException) -> None:
        self.test_mic_btn.setEnabled(self.orb.isEnabled())
        self.status_label.setText(f"Microphone test failed: {exc}")

    def _update_live_level(self) -> None:
        if self._recorder is not None:
            self._set_level(getattr(self._recorder, "last_rms", lambda: 0.0)())

    def _set_level(self, rms: float) -> None:
        percent = min(100, max(0, round(rms / INPUT_LEVEL_FULL_SCALE * 100)))
        self.level_bar.setValue(percent)
        self.level_label.setText(f"Input level: {rms:.0f}")

    # ---- options ----

    def _on_speak_toggled(self, checked: bool) -> None:
        self.chat_service.config.read_replies_aloud = checked
        if self.config_store is not None:
            self.config_store.save(self.chat_service.config)

    def show_command_response(self, text: str) -> None:
        self.status_label.setText(text)
