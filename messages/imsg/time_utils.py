from datetime import datetime, timezone

from imsg.constants import APPLE_EPOCH

_NS_THRESHOLD: int = 10**11


def apple_to_dt(raw: int | float | None) -> datetime | None:
    if not raw:
        return None
    # `message.date` etc. are integer ns since 2001; `message_summary_info.d` is a float in
    # *seconds* since 2001. Threshold separates them cleanly.
    if isinstance(raw, float) or raw < _NS_THRESHOLD:
        unix = float(raw) + APPLE_EPOCH
    else:
        unix = raw / 1_000_000_000 + APPLE_EPOCH
    return datetime.fromtimestamp(unix, tz=timezone.utc)


def dt_to_apple_ns(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt.timestamp() - APPLE_EPOCH) * 1_000_000_000)
