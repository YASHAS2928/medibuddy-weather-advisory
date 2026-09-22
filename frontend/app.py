import os
import uuid

import httpx
import streamlit as st

from frontend.presentation import trace_rows, uncovered_activity_rows, weather_rows


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
if not BACKEND_URL.startswith(("http://", "https://")):
    BACKEND_URL = f"http://{BACKEND_URL}"
BACKEND_URL = BACKEND_URL.rstrip("/")


def request_advisory(message: str, session_id: str) -> dict:
    try:
        response = httpx.post(
            f"{BACKEND_URL}/chat",
            json={"message": message, "session_id": session_id},
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise RuntimeError("The advisory service timed out. Please try again.") from exc
    except httpx.RequestError as exc:
        raise RuntimeError("The advisory service is unavailable. Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError("The advisory service could not complete the request.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("The advisory service returned an invalid response.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
        raise RuntimeError("The advisory service returned an invalid response.")
    return payload


def display_context(context: dict) -> None:
    values = [
        ("Location", context.get("location")),
        ("Activity", context.get("activity") or context.get("unsupported_activity")),
        ("Audience", context.get("audience")),
        ("Requested time", context.get("timeframe")),
    ]
    for label, value in values:
        if value:
            st.markdown(f"- **{label}:** {value}")


def display_explanation(payload: dict) -> None:
    with st.expander("Why this answer?"):
        context = payload.get("resolved_context") or {}
        if any(context.values()):
            st.markdown("**Resolved request**")
            display_context(context)

        place = payload.get("resolved_location")
        if place:
            st.markdown("**Resolved place**")
            location_parts = [place.get("name"), place.get("admin1"), place.get("country")]
            st.write(", ".join(part for part in location_parts if part))

        if payload.get("target_time"):
            st.markdown("**Forecast time**")
            st.write(payload["target_time"])

        evidence = weather_rows(payload.get("weather"))
        if evidence:
            st.markdown("**Observed weather evidence**")
            st.table(evidence)

        candidate_ids = payload.get("candidate_policy_ids") or []
        if candidate_ids:
            st.markdown("**Candidate SOPs**")
            st.write(", ".join(candidate_ids))

        matches = payload.get("matched_policies") or []
        if matches:
            st.markdown("**Policies applied**")
            for match in matches:
                st.markdown(
                    f"- **{match['policy_id']} — {match['title']}** "
                    f"({match['severity']}, priority {match['priority']})"
                )

        evaluations = payload.get("policy_evaluations") or []
        if evaluations:
            st.markdown("**Condition evaluation**")
            for evaluation in evaluations:
                st.markdown(
                    f"**{evaluation['policy_id']}** — "
                    f"{evaluation['status'].replace('_', ' ')}"
                )
                rows = trace_rows(evaluation.get("condition_trace"))
                if rows:
                    st.dataframe(rows, hide_index=True, width="stretch")

        if payload.get("status") == "no_policy_match" and candidate_ids:
            st.caption("None of the candidate SOP trigger conditions matched.")
        uncovered = uncovered_activity_rows(payload)
        if uncovered:
            st.markdown("**Policy coverage**")
            st.table(uncovered)


def display_assistant(payload: dict) -> None:
    st.markdown(payload["message"])
    display_explanation(payload)


st.set_page_config(page_title="Weather Advisory Support Bot")
st.title("Weather Advisory Support Bot")
st.caption("Policy-grounded weather guidance with reviewer-visible evidence.")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

for item in st.session_state.messages:
    with st.chat_message(item["role"]):
        if item["role"] == "assistant" and item.get("payload"):
            display_assistant(item["payload"])
        else:
            st.markdown(item["content"])

if prompt := st.chat_input("Ask about a weather-sensitive activity"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            payload = request_advisory(prompt, st.session_state.session_id)
            display_assistant(payload)
            assistant_item = {
                "role": "assistant",
                "content": payload["message"],
                "payload": payload,
            }
        except RuntimeError as exc:
            st.error(str(exc))
            assistant_item = {"role": "assistant", "content": str(exc)}
    st.session_state.messages.append(assistant_item)
