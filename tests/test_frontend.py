from frontend.presentation import (
    operator_label,
    trace_rows,
    uncovered_activity_rows,
    weather_rows,
)


def test_weather_rows_use_human_labels_units_and_structured_values():
    rows = weather_rows({
        "wind_speed_kmh": 46.2,
        "precipitation_probability": 70,
        "latitude": 23.2,
        "observed_at": "2026-09-22T20:00:00+05:30",
    })

    assert rows == [
        {"Weather evidence": "Precipitation probability", "Value": 70, "Unit": "%"},
        {"Weather evidence": "Wind speed", "Value": 46.2, "Unit": "km/h"},
    ]


def test_operator_labels_are_for_presentation_only():
    assert operator_label("gt") == ">"
    assert operator_label("gte") == ">="
    assert operator_label("lt") == "<"
    assert operator_label("lte") == "<="
    assert operator_label("eq") == "="
    assert operator_label("in") == "in"
    assert operator_label("between") == "between"


def test_nested_trace_is_flattened_without_evaluating_it_again():
    trace = {
        "kind": "all",
        "status": "evaluated",
        "result": True,
        "children": [
            {
                "kind": "leaf",
                "status": "evaluated",
                "result": True,
                "field": "wind_speed_kmh",
                "operator": "gte",
                "actual_value": 46.2,
                "expected_value": 40,
                "margin": 6.2,
            },
            {
                "kind": "leaf",
                "status": "missing_evidence",
                "result": None,
                "field": "precipitation_mm",
                "operator": "gte",
                "actual_value": None,
                "expected_value": 5,
                "margin": None,
            },
        ],
    }

    rows = trace_rows(trace)

    assert rows[0] == {
        "Field": "Wind speed",
        "Actual": 46.2,
        "Operator": ">=",
        "Expected": 40,
        "Unit": "km/h",
        "Result": "Matched",
        "Margin": 6.2,
    }
    assert rows[1]["Result"] == "Missing evidence"


def test_uncovered_activity_trace_explains_coverage_and_skipped_weather():
    rows = uncovered_activity_rows({
        "status": "no_applicable_policy",
        "resolved_context": {"unsupported_activity": "swimming"},
        "weather": None,
    })

    assert rows == [
        {"Review detail": "Requested activity", "Value": "swimming"},
        {
            "Review detail": "Policy coverage",
            "Value": "No configured SOP currently covers this activity.",
        },
        {"Review detail": "Weather evidence", "Value": "Not requested"},
    ]
