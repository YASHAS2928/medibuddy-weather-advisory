WEATHER_FIELDS = {
    "temperature_c": ("Temperature", "°C"),
    "apparent_temperature_c": ("Apparent temperature", "°C"),
    "precipitation_mm": ("Precipitation", "mm"),
    "precipitation_probability": ("Precipitation probability", "%"),
    "wind_speed_kmh": ("Wind speed", "km/h"),
    "wind_gust_kmh": ("Wind gust", "km/h"),
    "uv_index": ("UV index", ""),
    "weather_code": ("Weather code", ""),
    "visibility_m": ("Visibility", "m"),
}

OPERATORS = {
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "eq": "=",
    "in": "in",
    "between": "between",
}


def weather_rows(weather: dict | None) -> list[dict]:
    if not weather:
        return []
    rows = []
    for field, (label, unit) in WEATHER_FIELDS.items():
        value = weather.get(field)
        if value is not None:
            rows.append({"Weather evidence": label, "Value": value, "Unit": unit})
    return rows


def operator_label(operator: str | None) -> str:
    if operator is None:
        return ""
    return OPERATORS.get(operator, operator)


def uncovered_activity_rows(payload: dict) -> list[dict]:
    context = payload.get("resolved_context") or {}
    activity = context.get("unsupported_activity")
    if payload.get("status") != "no_applicable_policy" or not activity:
        return []
    return [
        {"Review detail": "Requested activity", "Value": activity},
        {
            "Review detail": "Policy coverage",
            "Value": "No configured SOP currently covers this activity.",
        },
        {"Review detail": "Weather evidence", "Value": "Not requested"},
    ]


def trace_rows(trace: dict | None) -> list[dict]:
    if not trace:
        return []
    children = trace.get("children") or []
    if children:
        rows = []
        for child in children:
            rows.extend(trace_rows(child))
        return rows
    if trace.get("field") is None:
        return []
    status = trace.get("status")
    result = trace.get("result")
    if status == "missing_evidence":
        result_label = "Missing evidence"
    elif result:
        result_label = "Matched"
    else:
        result_label = "Not matched"
    label, unit = WEATHER_FIELDS.get(
        trace["field"],
        (trace["field"].replace("_", " ").title(), ""),
    )
    return [{
        "Field": label,
        "Actual": trace.get("actual_value"),
        "Operator": operator_label(trace.get("operator")),
        "Expected": trace.get("expected_value"),
        "Unit": unit,
        "Result": result_label,
        "Margin": trace.get("margin"),
    }]
