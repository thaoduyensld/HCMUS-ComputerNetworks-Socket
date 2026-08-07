"""Independent, thread-safe token bucket bandwidth limiter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from threading import Lock
from time import monotonic, sleep


Clock = Callable[[], float]
Sleeper = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class TokenBucketSnapshot:
    rate_bytes_per_second: float
    burst_bytes: float
    available_tokens: float
    total_bytes_consumed: float
    total_wait_seconds: float


class TokenBucket:
    """Limit one session to a byte rate while allowing a bounded burst.

    ``consume`` may be called with an amount larger than the bucket capacity;
    it consumes the amount in bounded installments. Sleeping always happens
    outside the state lock so one waiting consumer cannot block inspection or
    another consumer using the same limiter.
    """

    def __init__(
        self,
        rate_bytes_per_second: int | float,
        burst_bytes: int | float,
        *,
        initial_tokens: int | float | None = None,
        clock: Clock = monotonic,
        sleeper: Sleeper = sleep,
    ) -> None:
        self.rate_bytes_per_second = _positive_number(
            rate_bytes_per_second,
            "rate_bytes_per_second",
        )
        self.burst_bytes = _positive_number(burst_bytes, "burst_bytes")
        starting_tokens = (
            self.burst_bytes
            if initial_tokens is None
            else _nonnegative_number(initial_tokens, "initial_tokens")
        )
        if starting_tokens > self.burst_bytes:
            raise ValueError("initial_tokens must not exceed burst_bytes")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(sleeper):
            raise TypeError("sleeper must be callable")

        self._clock = clock
        self._sleeper = sleeper
        self._lock = Lock()
        self._tokens = starting_tokens
        self._last_refill = float(clock())
        self._total_bytes_consumed = 0.0
        self._total_wait_seconds = 0.0

    def consume(self, amount: int) -> float:
        """Block until *amount* bytes are admitted and return requested wait."""

        remaining = float(_byte_amount(amount))
        waited = 0.0
        while remaining > 0:
            with self._lock:
                self._refill_locked()
                consumed = min(self._tokens, remaining)
                self._tokens -= consumed
                remaining -= consumed
                self._total_bytes_consumed += consumed
                if remaining <= 0:
                    return waited
                wait_seconds = min(remaining, self.burst_bytes) / (
                    self.rate_bytes_per_second
                )

            self._sleeper(wait_seconds)
            waited += wait_seconds
            with self._lock:
                self._total_wait_seconds += wait_seconds
        return waited

    def try_consume(self, amount: int) -> bool:
        """Consume immediately when enough tokens exist; never sleep."""

        requested = float(_byte_amount(amount))
        with self._lock:
            self._refill_locked()
            if requested > self._tokens:
                return False
            self._tokens -= requested
            self._total_bytes_consumed += requested
            return True

    def snapshot(self) -> TokenBucketSnapshot:
        """Return an atomic state snapshot after applying elapsed refill."""

        with self._lock:
            self._refill_locked()
            return TokenBucketSnapshot(
                rate_bytes_per_second=self.rate_bytes_per_second,
                burst_bytes=self.burst_bytes,
                available_tokens=self._tokens,
                total_bytes_consumed=self._total_bytes_consumed,
                total_wait_seconds=self._total_wait_seconds,
            )

    @property
    def available_tokens(self) -> float:
        return self.snapshot().available_tokens

    def _refill_locked(self) -> None:
        now = float(self._clock())
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(
            self.burst_bytes,
            self._tokens + elapsed * self.rate_bytes_per_second,
        )
        self._last_refill = now


def _positive_number(value: int | float, name: str) -> float:
    number = _finite_number(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def _nonnegative_number(value: int | float, name: str) -> float:
    number = _finite_number(value, name)
    if number < 0:
        raise ValueError(f"{name} must not be negative")
    return number


def _finite_number(value: int | float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _byte_amount(amount: int) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError("amount must be an integer byte count")
    if amount < 0:
        raise ValueError("amount must not be negative")
    return amount
