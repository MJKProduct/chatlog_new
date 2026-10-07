from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class Clock:
    def __init__(self, now: datetime | None = None) -> None:
        self._fixed = now

    def utcnow(self) -> datetime:
        if self._fixed is not None:
            if self._fixed.tzinfo is None:
                return self._fixed.replace(tzinfo=timezone.utc)
            return self._fixed.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def to_display(self, dt: datetime, tz_name: str) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz_name)).isoformat()
