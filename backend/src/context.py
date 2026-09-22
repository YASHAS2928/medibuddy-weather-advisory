from backend.src.models import IntentUpdate, UserContext


def merge_context(
    previous_context: UserContext | None,
    intent_update: IntentUpdate,
) -> UserContext:
    merged = previous_context.model_copy(deep=True) if previous_context else UserContext()

    if intent_update.location is not None:
        merged.location = intent_update.location
    if intent_update.activity is not None:
        merged.activity = intent_update.activity
        merged.unsupported_activity = None
    elif intent_update.unsupported_activity is not None:
        merged.activity = None
        merged.unsupported_activity = intent_update.unsupported_activity
    if intent_update.audience is not None:
        merged.audience = intent_update.audience
    if intent_update.time_reference is not None:
        merged.timeframe = intent_update.time_reference.context_value()

    return merged
