"""Injectable clocks. All instants are timezone-aware; storage uses UTC."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    @property
    def is_fixed(self) -> bool: ...


class SystemClock:
    is_fixed = False

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A controllable clock for demo sessions, fixtures and tests."""

    is_fixed = True

    def __init__(self, instant: datetime):
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        self._now = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        self._now = instant.astimezone(UTC)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed")
    return dt.astimezone(UTC)


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else to_utc(dt).isoformat()


def parse_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"stored instant {s!r} lacks offset")
    return dt
