"""Serialized background execution for the Tkinter frontend."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Generic, TypeVar


Result = TypeVar("Result")
Operation = Callable[[], object]
_STOP = object()


class UiEventKind(Enum):
    TASK_STARTED = auto()
    TASK_COMPLETED = auto()
    TASK_FAILED = auto()
    TRANSFER_PROGRESS = auto()


@dataclass(frozen=True, slots=True)
class UiEvent(Generic[Result]):
    kind: UiEventKind
    task_name: str
    payload: Result | None = None
    error: Exception | None = None


class BackgroundWorker:
    """Execute submitted operations sequentially outside Tk's main thread."""

    def __init__(self, *, thread_name: str = "hcmus-ui-worker") -> None:
        self.events: Queue[UiEvent[object]] = Queue()
        self._tasks: Queue[tuple[str, Operation] | object] = Queue()
        self._closed = Event()
        self._lock = Lock()
        self._thread = Thread(
            target=self._run,
            name=thread_name,
            daemon=True,
        )
        self._thread.start()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, task_name: str, operation: Operation) -> None:
        if not task_name:
            raise ValueError("task_name must not be empty")
        if not callable(operation):
            raise TypeError("operation must be callable")
        with self._lock:
            if self._closed.is_set():
                raise RuntimeError("background worker is closed")
            self._tasks.put((task_name, operation))

    def emit_progress(self, task_name: str, payload: object) -> None:
        if not self._closed.is_set():
            self.events.put(
                UiEvent(UiEventKind.TRANSFER_PROGRESS, task_name, payload=payload)
            )

    def poll(self) -> UiEvent[object] | None:
        try:
            return self.events.get_nowait()
        except Empty:
            return None

    def close(self, *, timeout: float = 1.0) -> None:
        with self._lock:
            if not self._closed.is_set():
                self._closed.set()
                self._tasks.put(_STOP)
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            task = self._tasks.get()
            if task is _STOP:
                return
            task_name, operation = task
            self.events.put(UiEvent(UiEventKind.TASK_STARTED, task_name))
            try:
                result = operation()
            except Exception as error:
                self.events.put(
                    UiEvent(UiEventKind.TASK_FAILED, task_name, error=error)
                )
            else:
                self.events.put(
                    UiEvent(UiEventKind.TASK_COMPLETED, task_name, payload=result)
                )
