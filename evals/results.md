# Evaluation Results

Generated: 2026-09-22T17:49:33.512774+00:00

Suite mode: deterministic graph evaluation with frozen intent, geocoding, and weather boundaries.

## Summary

- Passed: 20
- Failed: 0
- Skipped: 0
- Total deterministic cases: 20

## Deterministic cases

| Case | Category | Result | Actual | Duration |
|---|---|---:|---|---:|
| `direct_wind_match` | direct_policy_match | **PASS** | final status=success; matches=['SOP-WIND-CYCLING-01'] | 97.3 ms |
| `direct_wind_nonmatch` | non_triggering_condition | **PASS** | final status=no_policy_match; matches=[] | 75.6 ms |
| `fuzzy_picnic_family` | paraphrased_request | **PASS** | final status=success; matches=['SOP-RAIN-PICNIC-01'] | 72.2 ms |
| `paraphrase_outdoor_gathering` | paraphrased_request | **PASS** | final status=success; matches=['SOP-RAIN-PICNIC-01'] | 70.5 ms |
| `multiple_policy_matches` | multiple_simultaneous_matches | **PASS** | final status=success; matches=['SOP-THUNDER-OUTDOOR-01', 'SOP-RAIN-WIND-EVENT-01', 'SOP-UV-PROLONGED-OUTDOOR-01'] | 72.4 ms |
| `vulnerable_elderly_heat` | vulnerable_person | **PASS** | final status=success; matches=['SOP-HEAT-ELDERLY-01'] | 75.7 ms |
| `follow_up_memory` | conversation_follow_up | **PASS** | final status=no_policy_match; matches=[] | 112.3 ms |
| `session_isolation` | session_isolation | **PASS** | final status=missing_context; matches=[] | 80.5 ms |
| `location_change` | conversation_follow_up | **PASS** | final status=success; matches=['SOP-WIND-CYCLING-01'] | 94.8 ms |
| `unsupported_activity_coverage` | no_policy_coverage | **PASS** | final status=no_applicable_policy; matches=[] | 65.2 ms |
| `missing_location` | missing_context | **PASS** | final status=missing_context; matches=[] | 58.3 ms |
| `invalid_location` | location_failure | **PASS** | final status=location_error; matches=[] | 61.7 ms |
| `weather_service_failure` | weather_failure | **PASS** | final status=weather_error; matches=[] | 111.2 ms |
| `missing_weather_evidence` | missing_evidence | **PASS** | final status=no_policy_match; matches=[] | 74.4 ms |
| `adversarial_policy_override` | adversarial_behavior | **PASS** | final status=success; matches=['SOP-WIND-CYCLING-01'] | 78.3 ms |
| `adversarial_fake_weather` | adversarial_behavior | **PASS** | final status=success; matches=['SOP-WIND-CYCLING-01'] | 73.8 ms |
| `evidence_minimization_cycling` | evidence_plan_correctness | **PASS** | final status=no_policy_match; matches=[] | 72.4 ms |
| `dynamic_sop_extension` | policy_extensibility | **PASS** | final status=success; matches=['SOP-WIND-KAYAKING-EVAL-01'] | 73.8 ms |
| `frozen_bhopal_severe_heat` | severe_weather_regression | **PASS** | final status=success; matches=['SOP-HEAT-EXERCISE-01'] | 80.6 ms |
| `stale_evidence_after_failure` | stale_state_regression | **PASS** | final status=weather_error; matches=[] | 98.0 ms |

## Failure details

No deterministic failures were recorded.
## Live evaluations

| Check | Result | Detail |
|---|---:|---|
| Open-Meteo integration | **PASS** | Resolved Bhopal; requested ['wind_speed_kmh']; normalized wind_speed_kmh=11.2; graph status=no_policy_match. |
| LLM semantic extraction | **PASS** | 8 structured semantic cases passed. |

## Severe-weather provenance

The severe regression uses a frozen Open-Meteo Historical Weather API row for Bhopal at 2024-05-20 13:00 Asia/Kolkata. The archived apparent temperature is 44.0 °C, which exceeds the existing 40 °C severe exercise SOP threshold. The endpoint, coordinates, timestamp, units, provider row, and retrieval timestamp are stored in `evals/fixtures/bhopal_heat_2024-05-20.json`. Live provider checks confirm current integration health; this frozen row keeps policy behavior repeatable after the weather event passes.

## Known limitations

- Deterministic paraphrase cases validate the downstream structured-intent pipeline, not real model semantic interpretation.
- Live LLM semantics are evaluated only when both `LLM_API_KEY` and `LLM_MODEL` are configured.
- An unknown activity may be represented as an absent activity. The planner then considers broad policies instead of proving that no SOP covers the user's actual activity; the no-coverage case records this behavior as a failure if it occurs.
- In-memory graph checkpoints remain process-local by design.

## Interpretation

20 of 20 deterministic cases passed. Failures above are preserved as observed and were not converted into passes. Deterministic results use the real policy loader, context merge, time resolver, evidence planner, policy engine, LangGraph routing, and response construction.
