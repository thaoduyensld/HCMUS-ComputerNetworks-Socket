from __future__ import annotations

from threading import Event
from time import monotonic, sleep

import pytest

from hcmus_socket.ui.worker import BackgroundWorker, UiEvent, UiEventKind


def collect(worker: BackgroundWorker, count: int) -> list[UiEvent[object]]:
    events: list[UiEvent[object]] = []
    deadline = monotonic() + 2
    while len(events) < count:
        event = worker.poll()
        if event is not None:
            events.append(event)
        elif monotonic() >= deadline:
            raise AssertionError("worker events did not arrive")
        else:
            sleep(0.001)
    return events


def test_worker_executes_tasks_sequentially_and_reports_results() -> None:
    worker = BackgroundWorker()
    first_release = Event()
    order: list[str] = []

    def first() -> int:
        order.append("first-start")
        assert first_release.wait(timeout=2)
        order.append("first-end")
        return 1

    def second() -> int:
        order.append("second")
        return 2

    try:
        worker.submit("first", first)
        worker.submit("second", second)
        assert collect(worker, 1)[0].kind is UiEventKind.TASK_STARTED
        first_release.set()
        events = collect(worker, 3)
    finally:
        worker.close()

    assert order == ["first-start", "first-end", "second"]
    assert [(event.kind, event.task_name, event.payload) for event in events] == [
        (UiEventKind.TASK_COMPLETED, "first", 1),
        (UiEventKind.TASK_STARTED, "second", None),
        (UiEventKind.TASK_COMPLETED, "second", 2),
    ]


def test_worker_reports_failure_and_continues() -> None:
    worker = BackgroundWorker()
    try:
        worker.submit("broken", lambda: (_ for _ in ()).throw(ValueError("bad")))
        worker.submit("healthy", lambda: "ok")
        events = collect(worker, 4)
    finally:
        worker.close()

    assert events[1].kind is UiEventKind.TASK_FAILED
    assert isinstance(events[1].error, ValueError)
    assert events[-1].payload == "ok"


def test_progress_event_and_closed_worker_validation() -> None:
    worker = BackgroundWorker()
    worker.emit_progress("upload", (1, 2, 50))
    progress = collect(worker, 1)[0]
    worker.close()

    assert progress.kind is UiEventKind.TRANSFER_PROGRESS
    assert progress.payload == (1, 2, 50)
    with pytest.raises(RuntimeError, match="closed"):
        worker.submit("late", lambda: None)
