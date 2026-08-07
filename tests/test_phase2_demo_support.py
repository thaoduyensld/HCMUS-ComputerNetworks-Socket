from __future__ import annotations

import pytest

from scripts.phase2_demo_support import throughput_kib_per_second, within_limit


def test_throughput_uses_binary_kibibytes() -> None:
    assert throughput_kib_per_second(1024 * 500, 2.0) == 250.0


def test_bandwidth_tolerance_is_inclusive() -> None:
    assert within_limit(550.0, 500.0, 10.0)
    assert not within_limit(550.001, 500.0, 10.0)


@pytest.mark.parametrize(
    ("measured", "limit", "tolerance"),
    [(1.0, 0.0, 10.0), (1.0, -1.0, 10.0), (1.0, 1.0, -0.1)],
)
def test_bandwidth_validation(
    measured: float,
    limit: float,
    tolerance: float,
) -> None:
    with pytest.raises(ValueError):
        within_limit(measured, limit, tolerance)
