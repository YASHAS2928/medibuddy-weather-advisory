from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.src.models import TimeReference, TimeReferenceKind


PART_OF_DAY_HOURS = {
    TimeReferenceKind.MORNING: 9,
    TimeReferenceKind.MIDDAY: 13,
    TimeReferenceKind.AFTERNOON: 15,
    TimeReferenceKind.EVENING: 19,
    TimeReferenceKind.TONIGHT: 20,
    TimeReferenceKind.TOMORROW_MORNING: 9,
    TimeReferenceKind.TOMORROW_MIDDAY: 13,
    TimeReferenceKind.TOMORROW_AFTERNOON: 15,
    TimeReferenceKind.TOMORROW_EVENING: 19,
    TimeReferenceKind.TOMORROW_NIGHT: 20,
}


class TimeResolutionError(ValueError):
    pass


def resolve_target_time(
    reference: TimeReference,
    timezone: str,
    now: datetime | None = None,
) -> datetime:
    zone = _load_timezone(timezone)
    if now is None:
        current = datetime.now(zone)
    else:
        if now.tzinfo is None or now.utcoffset() is None:
            raise TimeResolutionError("Current time must be timezone-aware")
        current = now.astimezone(zone)

    if reference.hour is not None:
        day_offset = 1 if reference.kind is TimeReferenceKind.TOMORROW else 0
        target_date = current.date() + timedelta(days=day_offset)
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            reference.hour,
            reference.minute or 0,
            tzinfo=zone,
        )

    if reference.kind in {TimeReferenceKind.NOW, TimeReferenceKind.TODAY}:
        return current

    if reference.kind is TimeReferenceKind.TOMORROW:
        return current + timedelta(days=1)

    day_offset = 1 if reference.kind.value.startswith("tomorrow_") else 0
    target_date = current.date() + timedelta(days=day_offset)
    hour = PART_OF_DAY_HOURS[reference.kind]
    return datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        hour,
        tzinfo=zone,
    )


def _load_timezone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimeResolutionError(f"Invalid timezone '{timezone}'") from exc
