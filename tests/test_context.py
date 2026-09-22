from backend.src.context import merge_context
from backend.src.models import IntentUpdate, TimeReference, TimeReferenceKind, UserContext


def test_follow_up_preserves_context_and_updates_time():
    previous = UserContext(
        location="Bhopal",
        activity="cycling",
        audience="adult",
        timeframe="evening",
    )
    update = IntentUpdate(
        time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW_MORNING)
    )

    merged = merge_context(previous, update)
    assert merged == UserContext(
        location="Bhopal",
        activity="cycling",
        audience="adult",
        timeframe="tomorrow_morning",
    )


def test_explicit_location_change_preserves_activity():
    previous = UserContext(location="Bhopal", activity="cycling")
    merged = merge_context(previous, IntentUpdate(location="Indore"))
    assert merged.location == "Indore"
    assert merged.activity == "cycling"


def test_generic_venue_intent_retains_previous_geographic_context():
    previous = UserContext(
        location="Bhopal",
        activity="cycling",
        audience="adult",
        timeframe="tonight",
    )
    update = IntentUpdate(
        location=None,
        activity="picnic",
        audience="general",
        time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW_MIDDAY),
    )

    merged = merge_context(previous, update)

    assert merged == UserContext(
        location="Bhopal",
        activity="picnic",
        audience="general",
        timeframe="tomorrow_midday",
    )


def test_explicit_activity_change_replaces_activity():
    previous = UserContext(location="Bhopal", activity="cycling")
    merged = merge_context(previous, IntentUpdate(activity="walking"))
    assert merged.location == "Bhopal"
    assert merged.activity == "walking"


def test_uncovered_activity_clears_supported_activity():
    previous = UserContext(location="Bhopal", activity="cycling")
    merged = merge_context(
        previous,
        IntentUpdate(unsupported_activity="swimming"),
    )

    assert merged.activity is None
    assert merged.unsupported_activity == "swimming"


def test_follow_up_without_activity_retains_uncovered_activity():
    previous = UserContext(location="Bhopal", unsupported_activity="swimming")
    merged = merge_context(
        previous,
        IntentUpdate(
            time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW_MORNING)
        ),
    )

    assert merged.activity is None
    assert merged.unsupported_activity == "swimming"
    assert merged.timeframe == "tomorrow_morning"


def test_supported_activity_clears_uncovered_activity():
    previous = UserContext(location="Bhopal", unsupported_activity="swimming")
    merged = merge_context(previous, IntentUpdate(activity="cycling"))

    assert merged.activity == "cycling"
    assert merged.unsupported_activity is None


def test_first_turn_builds_context_without_inventing_audience():
    update = IntentUpdate(
        location="Bhopal",
        activity="cycling",
        time_reference=TimeReference(kind=TimeReferenceKind.TONIGHT),
    )
    merged = merge_context(None, update)
    assert merged == UserContext(
        location="Bhopal",
        activity="cycling",
        audience=None,
        timeframe="tonight",
    )


def test_explicit_hour_has_stable_context_value():
    update = IntentUpdate(time_reference=TimeReference(
        kind=TimeReferenceKind.TOMORROW,
        hour=18,
        minute=30,
    ))
    assert merge_context(None, update).timeframe == "tomorrow_at_18:30"
