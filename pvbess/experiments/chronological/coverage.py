# complete onset windows
from __future__ import annotations


def complete_hourly_intervals(
    point_count: int, interval_count: int
) -> tuple[int, ...]:
    if point_count < 1: raise ValueError("point_count must be positive")
    if interval_count < 1: raise ValueError("interval_count must be positive")
    n0 = point_count - interval_count + 1
    if n0 <= 0:
        raise ValueError("interval window exceeds the chronology")
    tmp = tuple(range(n0))
    return tmp
