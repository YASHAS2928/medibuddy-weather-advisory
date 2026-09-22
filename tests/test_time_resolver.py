from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.src.models import TimeReference, TimeReferenceKind
from backend.src.time_resolver import TimeResolutionError, resolve_target_time


KOLKATA_NOW = datetime(2026, 9, 22, 16, 30, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_now_and_today_use_injected_current_time():
    now_target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.NOW),
        "Asia/Kolkata",
        KOLKATA_NOW,
    )
    today_target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.TODAY),
        "Asia/Kolkata",
        KOLKATA_NOW,
    )
    assert now_target == KOLKATA_NOW
    assert today_target == KOLKATA_NOW


def test_tomorrow_morning_is_next_day_at_0900():
    target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.TOMORROW_MORNING),
        "Asia/Kolkata",
        KOLKATA_NOW,
    )
    assert target == datetime(2026, 9, 23, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_tomorrow_midday_is_next_day_at_1300():
    target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.TOMORROW_MIDDAY),
        "Asia/Kolkata",
        KOLKATA_NOW,
    )
    assert target == datetime(2026, 9, 23, 13, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_tomorrow_evening_is_next_day_at_1900():
    target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.TOMORROW_EVENING),
        "Asia/Kolkata",
        KOLKATA_NOW,
    )
    assert target == datetime(2026, 9, 23, 19, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_tonight_stays_on_same_day_even_if_default_has_passed():
    late_now = datetime(2026, 9, 22, 21, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
    target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.TONIGHT),
        "Asia/Kolkata",
        late_now,
    )
    assert target == datetime(2026, 9, 22, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_explicit_tomorrow_hour_resolves_in_python():
    target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.TOMORROW, hour=18, minute=0),
        "Asia/Kolkata",
        KOLKATA_NOW,
    )
    assert target == datetime(2026, 9, 23, 18, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_explicit_hour_representation_overrides_broad_period():
    reference = TimeReference(
        kind=TimeReferenceKind.TOMORROW,
        hour=18,
        minute=0,
    )
    target = resolve_target_time(reference, "Asia/Kolkata", KOLKATA_NOW)
    assert target == datetime(2026, 9, 23, 18, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_resolver_uses_requested_timezone_not_hardcoded_ist():
    utc_now = datetime(2026, 9, 22, 12, 0, tzinfo=ZoneInfo("UTC"))
    target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.EVENING),
        "America/New_York",
        utc_now,
    )
    assert target == datetime(
        2026, 9, 22, 19, 0, tzinfo=ZoneInfo("America/New_York")
    )


def test_invalid_timezone_fails_clearly():
    with pytest.raises(TimeResolutionError, match="Invalid timezone"):
        resolve_target_time(
            TimeReference(kind=TimeReferenceKind.NOW),
            "Not/A_Timezone",
            KOLKATA_NOW,
        )


def test_naive_injected_current_time_is_rejected():
    with pytest.raises(TimeResolutionError, match="timezone-aware"):
        resolve_target_time(
            TimeReference(kind=TimeReferenceKind.NOW),
            "Asia/Kolkata",
            datetime(2026, 9, 22, 16, 30),
        )


def test_same_day_morning_does_not_silently_move_to_tomorrow():
    target = resolve_target_time(
        TimeReference(kind=TimeReferenceKind.MORNING),
        "Asia/Kolkata",
        KOLKATA_NOW,
    )
    assert target == datetime(2026, 9, 22, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_time_reference_rejects_hour_with_part_of_day():
    with pytest.raises(ValueError, match="explicit hours require today or tomorrow"):
        TimeReference(kind=TimeReferenceKind.EVENING, hour=18)
