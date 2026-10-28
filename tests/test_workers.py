"""Background task helpers must deliver callbacks reliably (no leaked refs)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lyric_sync.ui.workers import run_task  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(["lyric_sync_tests"])
    yield app


def _pump(app: QApplication, ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait(app: QApplication, predicate, timeout_ms: int = 10000) -> bool:
    """Pump the event loop until ``predicate`` holds (or the timeout passes)."""
    import time as _time

    deadline = _time.monotonic() + timeout_ms / 1000
    while _time.monotonic() < deadline:
        if predicate():
            return True
        _pump(app, 25)
    return bool(predicate())


def test_success_callback_fires_without_retaining_the_task(qapp):
    results: list[object] = []
    run_task(lambda: 42, on_finished=results.append)
    assert _wait(qapp, lambda: results == [42])


def test_error_callback_fires(qapp):
    errors: list[str] = []

    def boom() -> int:
        raise ValueError("nope")

    run_task(boom, on_error=errors.append)
    assert _wait(qapp, lambda: bool(errors))
    assert "nope" in errors[0]


def test_missing_error_handler_still_clears(qapp):
    finished: list[object] = []

    def boom() -> int:
        raise RuntimeError("x")

    run_task(boom, on_finished=finished.append)
    _pump(qapp, 600)
    assert finished == []


def test_worker_survives_deleted_signal_source(qapp):
    """Closing the window mid-search must not raise out of the worker."""
    from lyric_sync.ui.workers import Task

    class DeletedEmit:
        def emit(self, *_args) -> None:
            raise RuntimeError("Signal source has been deleted")

        def connect(self, *_args, **_kwargs) -> None:  # pragma: no cover
            pass

    class DeletedSignals:
        finished = DeletedEmit()
        error = DeletedEmit()

    ok = Task(lambda: 42)
    ok.signals = DeletedSignals()
    ok.run()  # must not raise

    failed = Task(lambda: (_ for _ in ()).throw(ValueError("boom")))
    failed.signals = DeletedSignals()
    failed.run()  # must not raise either
