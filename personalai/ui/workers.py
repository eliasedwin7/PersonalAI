"""TaskRunner: the one way background work happens in this GUI.

ChatService.send()/send_with_image() are blocking calls (they wait for
Ollama's HTTP response) - running them on the GUI thread would freeze
the window for the whole reply. QThreadPool + QRunnable moves that work
off-thread; a small per-task QObject carries the result/error/progress
back to the GUI thread via Qt's queued-connection signals (QRunnable
itself can't own signals).

Rule: only this module touches QThreadPool. Callbacks (on_result,
on_error, on_progress) always run back on the GUI thread, so it's safe
for them to touch widgets directly.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from personalai.core.errors import GenerationCancelled

log = logging.getLogger(__name__)


class _TaskSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    progress = Signal(object)
    cancelled = Signal()
    finished = Signal()


class TaskHandle:
    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel = cancel_event

    def cancel(self) -> None:
        self._cancel.set()


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], args: tuple, kwargs: dict,
                 signals: _TaskSignals, wants_progress: bool,
                 cancel_event: threading.Event) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = signals
        self.wants_progress = wants_progress
        self.cancel_event = cancel_event

    def run(self) -> None:
        try:
            kwargs = dict(self.kwargs)
            if self.wants_progress:
                kwargs["on_token"] = self._emit_progress
            result = self.fn(*self.args, **kwargs)
            if self.cancel_event.is_set():
                self._emit_safely(self.signals.cancelled)
                return
        except GenerationCancelled:
            self._emit_safely(self.signals.cancelled)
        except Exception as exc:
            log.exception("Worker task failed")
            self._emit_safely(self.signals.error, exc)
        else:
            self._emit_safely(self.signals.result, result)
        finally:
            self._emit_safely(self.signals.finished)

    def _emit_progress(self, token: Any) -> None:
        if self.cancel_event.is_set():
            raise GenerationCancelled()
        self.signals.progress.emit(token)

    @staticmethod
    def _emit_safely(signal, *args) -> None:
        # If the window is closing while a task is mid-flight, the C++
        # side of the signal bridge may already be gone - losing that
        # result is fine, crashing the worker thread is not.
        try:
            signal.emit(*args)
        except RuntimeError:
            pass


class TaskRunner(QObject):
    busy_changed = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self._in_flight = 0
        self._live_signals: set[_TaskSignals] = set()  # keep alive until finished

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_result: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[Any], None] | None = None,
        on_cancelled: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> TaskHandle:
        signals = _TaskSignals()
        if on_result:
            signals.result.connect(on_result)
        if on_error:
            signals.error.connect(on_error)
        else:
            signals.error.connect(lambda exc: log.error("Unhandled worker error: %s", exc))
        if on_progress:
            signals.progress.connect(on_progress)
        if on_cancelled:
            signals.cancelled.connect(on_cancelled)

        self._live_signals.add(signals)
        signals.finished.connect(lambda: self._on_finished(signals))

        self._in_flight += 1
        self.busy_changed.emit(self._in_flight)
        cancel_event = threading.Event()
        task = _Task(fn, args, kwargs, signals, on_progress is not None, cancel_event)
        self.pool.start(task)
        return TaskHandle(cancel_event)

    def _on_finished(self, signals: _TaskSignals) -> None:
        self._live_signals.discard(signals)
        self._in_flight -= 1
        try:
            self.busy_changed.emit(self._in_flight)
        except RuntimeError:
            # The TaskRunner's own C++ object can already be gone by the
            # time a background task's queued "finished" signal is
            # delivered - e.g. the window that owned it just closed.
            # Losing this one busy-count update is harmless; crashing
            # the Qt event loop over it is not.
            pass
