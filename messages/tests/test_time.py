from datetime import datetime, timezone

from imsg.time_utils import apple_to_dt, dt_to_apple_ns


def test_apple_to_dt_returns_none_for_falsy() -> None:
    assert apple_to_dt(None) is None
    assert apple_to_dt(0) is None


def test_apple_to_dt_int_nanoseconds() -> None:
    ns = 800_000_000 * 1_000_000_000
    dt = apple_to_dt(ns)
    assert dt == datetime(2026, 5, 9, 6, 13, 20, tzinfo=timezone.utc)


def test_apple_to_dt_int_seconds_legacy() -> None:
    dt = apple_to_dt(400_000_000)
    assert dt == datetime(2013, 9, 4, 15, 6, 40, tzinfo=timezone.utc)


def test_apple_to_dt_float_seconds_from_edit_summary() -> None:
    dt = apple_to_dt(801_207_710.0919569)
    assert dt is not None
    assert dt.year == 2026 and dt.month == 5
    assert dt.microsecond > 0


def test_dt_to_apple_ns_round_trip() -> None:
    dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ns = dt_to_apple_ns(dt)
    back = apple_to_dt(ns)
    assert back == dt


def test_dt_to_apple_ns_assumes_utc_when_naive() -> None:
    naive = datetime(2025, 1, 1, 12, 0, 0)
    aware = naive.replace(tzinfo=timezone.utc)
    assert dt_to_apple_ns(naive) == dt_to_apple_ns(aware)
