"""Background execution helpers.

All database work happens off the UI thread so the window stays responsive on
modest hardware (HP 255 G7 class).
"""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

# In-flight tasks, keyed by id(). Kept so callbacks/signals survive until the
# work completes (QThreadPool holds no reference to the Python wrapper).
_ACTIVE_TASKS: dict[int, "Task"] = {}

# The global pool defaults to the machine's core count (2 on entry-level
# laptops). Four workers keep song-open/favorites tasks from queueing behind
# two long searches without creating runaway threads.
QThreadPool.globalInstance().setMaxThreadCount(4)


class TaskSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class Task(QRunnable):
    """Run ``fn(*args, **kwargs)`` on the global thread pool."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:  # noqa: A003 - QRunnable API
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced through the signal
            traceback.print_exc()
            self._emit(str(exc) or exc.__class__.__name__, error=True)
        else:
            self._emit(result, error=False)

    def _emit(self, payload: Any, *, error: bool) -> None:
        """Emit without raising when the window is already torn down.

        Closing the application while a search is in flight must never raise
        "Signal source has been deleted" out of the worker.
        """
        try:
            if error:
                self.signals.error.emit(payload)
            else:
                self.signals.finished.emit(payload)
        except RuntimeError:
            pass


def run_task(
    fn: Callable[..., Any],
    *args: Any,
    on_finished: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> Task:
    """Schedule ``fn`` and wire up completion callbacks.

    The task is kept alive in a module-level registry until its callbacks
    fire; otherwise the pool holds no Python reference and the signals —
    and their receivers — can be collected while work is in flight.
    """
    task = Task(fn, *args, **kwargs)

    def _finish(result: Any) -> None:
        try:
            if on_finished is not None:
                on_finished(result)
        finally:
            _ACTIVE_TASKS.pop(id(task), None)

    def _fail(message: str) -> None:
        try:
            if on_error is not None:
                on_error(message)
        finally:
            _ACTIVE_TASKS.pop(id(task), None)

    task.signals.finished.connect(_finish)
    task.signals.error.connect(_fail)
    _ACTIVE_TASKS[id(task)] = task
    QThreadPool.globalInstance().start(task)
    return task


def run_in_pool(task: Task) -> None:
    _ACTIVE_TASKS[id(task)] = task
    QThreadPool.globalInstance().start(task)
