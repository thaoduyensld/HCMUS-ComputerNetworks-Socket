from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from hcmus_socket.throttling import TokenBucket


class FakeTime:
    def __init__(self) -> None:
        self._now = 0.0
        self._lock = Lock()
        self.sleeps: list[float] = []

    def clock(self) -> float:
        with self._lock:
            return self._now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleeps.append(seconds)
            self._now += seconds

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds


@pytest.mark.parametrize(
    ("rate", "burst"),
    [
        (0, 1),
        (-1, 1),
        (1, 0),
        (1, -1),
        (float("inf"), 1),
        (1, float("nan")),
    ],
)
def test_rejects_invalid_rate_and_burst(rate: float, burst: float) -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate, burst)


@pytest.mark.parametrize("value", [True, "100", None])
def test_rejects_non_numeric_configuration(value: object) -> None:
    with pytest.raises(TypeError):
        TokenBucket(value, 100)  # type: ignore[arg-type]


def test_initial_burst_is_immediate_and_tokens_refill_with_time() -> None:
    fake = FakeTime()
    bucket = TokenBucket(100, 200, clock=fake.clock, sleeper=fake.sleep)

    assert bucket.try_consume(200)
    assert not bucket.try_consume(1)
    fake.advance(0.5)
    assert bucket.try_consume(50)
    assert bucket.available_tokens == pytest.approx(0)


def test_consume_larger_than_burst_waits_in_bounded_installments() -> None:
    fake = FakeTime()
    bucket = TokenBucket(100, 100, clock=fake.clock, sleeper=fake.sleep)

    waited = bucket.consume(250)
    snapshot = bucket.snapshot()

    assert waited == pytest.approx(1.5)
    assert fake.sleeps == pytest.approx([1.0, 0.5])
    assert snapshot.total_bytes_consumed == pytest.approx(250)
    assert snapshot.total_wait_seconds == pytest.approx(1.5)
    assert snapshot.available_tokens == pytest.approx(0)


def test_zero_amount_is_a_noop() -> None:
    fake = FakeTime()
    bucket = TokenBucket(100, 100, clock=fake.clock, sleeper=fake.sleep)

    assert bucket.consume(0) == 0
    assert bucket.try_consume(0)
    assert fake.sleeps == []
    assert bucket.snapshot().total_bytes_consumed == 0


def test_two_limiters_have_independent_state() -> None:
    first_time = FakeTime()
    second_time = FakeTime()
    first = TokenBucket(
        100,
        100,
        initial_tokens=0,
        clock=first_time.clock,
        sleeper=first_time.sleep,
    )
    second = TokenBucket(
        100,
        100,
        clock=second_time.clock,
        sleeper=second_time.sleep,
    )

    assert first.consume(100) == pytest.approx(1.0)
    assert second.consume(100) == 0
    assert first_time.clock() == pytest.approx(1.0)
    assert second_time.clock() == 0


def test_sleep_does_not_hold_bucket_lock() -> None:
    fake = FakeTime()
    sleeping = Event()
    release = Event()

    def blocking_sleep(seconds: float) -> None:
        sleeping.set()
        assert release.wait(timeout=2)
        fake.advance(seconds)

    bucket = TokenBucket(
        100,
        100,
        initial_tokens=0,
        clock=fake.clock,
        sleeper=blocking_sleep,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(bucket.consume, 10)
        assert sleeping.wait(timeout=2)
        assert bucket.snapshot().available_tokens == 0
        release.set()
        assert future.result(timeout=2) == pytest.approx(0.1)


def test_try_consume_is_atomic_under_contention() -> None:
    fake = FakeTime()
    bucket = TokenBucket(1, 100, clock=fake.clock, sleeper=fake.sleep)

    with ThreadPoolExecutor(max_workers=32) as executor:
        results = list(executor.map(lambda _index: bucket.try_consume(1), range(1000)))

    assert sum(results) == 100
    assert bucket.snapshot().total_bytes_consumed == 100


@pytest.mark.parametrize("amount", [-1, 1.5, True])
def test_rejects_invalid_byte_amount(amount: object) -> None:
    bucket = TokenBucket(100, 100)
    expected = TypeError if not isinstance(amount, int) or isinstance(amount, bool) else ValueError
    with pytest.raises(expected):
        bucket.consume(amount)  # type: ignore[arg-type]
