# Evaluation Results

Generated: 2026-09-22T21:05:28.404769+00:00

Suite mode: deterministic graph evaluation with frozen intent, geocoding, and weather boundaries.

## Summary

- Passed: 20
- Failed: 0
- Skipped: 0
- Total deterministic cases: 20

## Deterministic cases

| Case | Category | Result | Actual | Duration |
|---|---|---:|---|---:|
| `direct_wind_match` | direct_policy_match | **PASS** | final status=success; matches=['SOP-WIND-CYCLING-01'] | 98.5 ms |
| `direct_wind_nonmatch` | non_triggering_condition | **PASS** | final status=no_policy_match; matches=[] | 73.3 ms |
| `fuzzy_picnic_family` | paraphrased_request | **PASS** | final status=success; matches=['SOP-RAIN-PICNIC-01'] | 83.8 ms |
| `paraphrase_outdoor_gathering` | paraphrased_request | **PASS** | final status=success; matches=['SOP-RAIN-PICNIC-01'] | 91.7 ms |
| `multiple_policy_matches` | multiple_simultaneous_matches | **PASS** | final status=success; matches=['SOP-THUNDER-OUTDOOR-01', 'SOP-RAIN-WIND-EVENT-01', 'SOP-UV-PROLONGED-OUTDOOR-01'] | 82.7 ms |
| `vulnerable_elderly_heat` | vulnerable_person | **PASS** | final status=success; matches=['SOP-HEAT-ELDERLY-01'] | 72.6 ms |
| `follow_up_memory` | conversation_follow_up | **PASS** | final status=no_policy_match; matches=[] | 90.1 ms |
| `session_isolation` | session_isolation | **PASS** | final status=missing_context; matches=[] | 82.1 ms |
| `location_change` | conversation_follow_up | **PASS** | final status=success; matches=['SOP-WIND-CYCLING-01'] | 108.6 ms |
| `unsupported_activity_coverage` | no_policy_coverage | **PASS** | final status=no_applicable_policy; matches=[] | 88.3 ms |
| `missing_location` | missing_context | **PASS** | final status=missing_context; matches=[] | 66.5 ms |
| `invalid_location` | location_failure | **PASS** | final status=location_error; matches=[] | 61.9 ms |
| `weather_service_failure` | weather_failure | **PASS** | final status=weather_error; matches=[] | 133.9 ms |
| `missing_weather_evidence` | missing_evidence | **PASS** | final status=no_policy_match; matches=[] | 70.3 ms |
| `adversarial_policy_override` | adversarial_behavior | **PASS** | final status=success; matches=['SOP-WIND-CYCLING-01'] | 68.3 ms |
| `adversarial_fake_weather` | adversarial_behavior | **PASS** | final status=success; matches=['SOP-WIND-CYCLING-01'] | 72.6 ms |
| `evidence_minimization_cycling` | evidence_plan_correctness | **PASS** | final status=no_policy_match; matches=[] | 72.1 ms |
| `dynamic_sop_extension` | policy_extensibility | **PASS** | final status=success; matches=['SOP-WIND-KAYAKING-EVAL-01'] | 78.7 ms |
| `frozen_bhopal_severe_heat` | severe_weather_regression | **PASS** | final status=success; matches=['SOP-HEAT-EXERCISE-01'] | 86.5 ms |
| `stale_evidence_after_failure` | stale_state_regression | **PASS** | final status=weather_error; matches=[] | 111.0 ms |

## Failure details

No deterministic failures were recorded.
## Live evaluations

| Check | Result | Detail |
|---|---:|---|
| Open-Meteo integration | **PASS** | Resolved Bhopal; requested ['wind_speed_kmh']; normalized wind_speed_kmh=16.0; graph status=no_policy_match. |
| LLM semantic extraction | **PASS** | 8 structured semantic cases passed. |

## Severe-weather provenance

The severe regression uses a frozen Open-Meteo Historical Weather API row for Bhopal at 2024-05-20 13:00 Asia/Kolkata. The archived apparent temperature is 44.0 °C, which exceeds the existing 40 °C severe exercise SOP threshold. The endpoint, coordinates, timestamp, units, provider row, and retrieval timestamp are stored in `evals/fixtures/bhopal_heat_2024-05-20.json`. Live provider checks confirm current integration health; this frozen row keeps policy behavior repeatable after the weather event passes.

## Known limitations

- Deterministic paraphrase cases validate the downstream structured-intent pipeline, not real model semantic interpretation.
- Live LLM semantics are evaluated only when both `LLM_API_KEY` and `LLM_MODEL` are configured.
- If the LLM misses an explicit unsupported activity, the planner may consider broad policies. The live semantic suite samples this failure mode but cannot prove coverage for every phrasing.
- In-memory graph checkpoints remain process-local by design.

## Interpretation

20 of 20 deterministic cases passed. Failures above are preserved as observed and were not converted into passes. Deterministic results use the real policy loader, context merge, time resolver, evidence planner, policy engine, LangGraph routing, and response construction.
