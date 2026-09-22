from backend.src.models import EvidencePlan, EvidenceRequirement, UserContext, WeatherFacts
from backend.src.policies import SOP, required_fields


class EvidencePlanningError(ValueError):
    pass


def build_evidence_plan(context: UserContext, policies: list[SOP]) -> EvidencePlan:
    if context.unsupported_activity is not None:
        return EvidencePlan()

    candidates = [policy for policy in policies if _is_candidate(policy, context)]
    candidate_policy_ids = sorted(policy.id for policy in candidates)
    field_sources: dict[str, set[str]] = {}
    supported_fields = set(WeatherFacts.model_fields)

    for policy in candidates:
        for field in required_fields(policy):
            if field not in supported_fields:
                raise EvidencePlanningError(
                    f"Unsupported weather field '{field}' referenced by policy {policy.id}"
                )
            field_sources.setdefault(field, set()).add(policy.id)

    requirements = []
    for field in sorted(field_sources):
        source_ids = sorted(field_sources[field])
        count = len(source_ids)
        policy_word = "policy" if count == 1 else "policies"
        requirements.append(
            EvidenceRequirement(
                field=field,
                required_by=source_ids,
                reason=f"Required to evaluate {count} candidate {policy_word}.",
            )
        )

    return EvidencePlan(
        requirements=requirements,
        candidate_policy_ids=candidate_policy_ids,
    )


def _is_candidate(policy: SOP, context: UserContext) -> bool:
    activities = set(policy.applies_to.activities)
    if context.activity is not None and context.activity not in activities:
        return False

    audiences = set(policy.applies_to.audiences)
    if (
        context.audience is not None
        and "general" not in audiences
        and context.audience not in audiences
    ):
        return False

    return True
