from __future__ import annotations

from datetime import datetime, timedelta


def as_local_naive_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def normalize_session_end_time(start_time: datetime, end_time: datetime) -> datetime:
    start = as_local_naive_datetime(start_time)
    end = as_local_naive_datetime(end_time)

    if end < start and end.date() == start.date():
        end = end + timedelta(days=1)

    if end < start:
        raise ValueError("end_time must be later than start_time when date is considered")

    return end


def calculate_duration_sec(start_time: datetime, end_time: datetime) -> int:
    start = as_local_naive_datetime(start_time)
    end = normalize_session_end_time(start, end_time)
    return int((end - start).total_seconds())
