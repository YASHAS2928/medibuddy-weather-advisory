import asyncio

import pytest

from evals.run_evals import (
    EvalResult,
    EvaluationConfigError,
    LiveResult,
    load_suite,
    run_case,
    write_report,
)


def test_case_yaml_loads_with_expected_categories_and_frozen_fixture():
    suite = load_suite()

    assert len(suite.cases) == 20
    assert len({case.id for case in suite.cases}) == 20
    assert "severe_weather_regression" in {case.category for case in suite.cases}
    severe = next(case for case in suite.cases if case.id == "frozen_bhopal_severe_heat")
    assert severe.turns[0].weather_fixture == "bhopal_heat_2024-05-20.json"


def test_invalid_case_schema_fails_clearly(tmp_path):
    path = tmp_path / "invalid.yaml"
    path.write_text("fixed_now: nope\nlocations: {}\ncases: []\n", encoding="utf-8")

    with pytest.raises(EvaluationConfigError, match="Invalid evaluation case schema"):
        load_suite(path)


def test_case_runner_passes_supported_and_uncovered_activity_cases():
    suite = load_suite()
    passing = next(case for case in suite.cases if case.id == "direct_wind_match")
    uncovered = next(
        case for case in suite.cases if case.id == "unsupported_activity_coverage"
    )

    pass_result = asyncio.run(run_case(passing, suite))
    uncovered_result = asyncio.run(run_case(uncovered, suite))

    assert pass_result.outcome == "PASS"
    assert uncovered_result.outcome == "PASS"
    assert uncovered_result.failures == []


def test_report_includes_failures_and_keeps_skip_distinct(tmp_path):
    results = [
        EvalResult("pass", "passes", "core", "PASS", "ok", "ok", 1.0),
        EvalResult(
            "fail",
            "fails",
            "core",
            "FAIL",
            "expected status=x",
            "actual status=y",
            2.0,
            ["status mismatch"],
        ),
        EvalResult("skip", "skips", "core", "SKIP", "n/a", "n/a", 0.0),
    ]
    live = [LiveResult("LLM semantic extraction", "SKIP", "not configured")]
    path = tmp_path / "results.md"

    write_report(results, live, path)
    report = path.read_text(encoding="utf-8")

    assert "Passed: 1" in report
    assert "Failed: 1" in report
    assert "Skipped: 1" in report
    assert "status mismatch" in report
    assert "LLM semantic extraction | **SKIP**" in report


def test_independent_cases_do_not_share_graph_state():
    suite = load_suite()
    established = next(case for case in suite.cases if case.id == "direct_wind_match")
    missing = next(case for case in suite.cases if case.id == "missing_location")

    first = asyncio.run(run_case(established, suite))
    second = asyncio.run(run_case(missing, suite))

    assert first.outcome == "PASS"
    assert second.outcome == "PASS"
