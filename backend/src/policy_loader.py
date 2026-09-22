from pathlib import Path

import yaml
from pydantic import ValidationError

from backend.src.policies import SOP


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "policies" / "sops.yaml"


class PolicyLoadError(ValueError):
    pass


def load_policies(path: str | Path = DEFAULT_POLICY_PATH) -> list[SOP]:
    policy_path = Path(path)
    try:
        with policy_path.open(encoding="utf-8") as policy_file:
            data = yaml.safe_load(policy_file)
    except yaml.YAMLError as exc:
        raise PolicyLoadError(f"Malformed policy YAML in {policy_path}: {exc}") from exc
    except OSError as exc:
        raise PolicyLoadError(f"Could not read policy file {policy_path}: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("sops"), list):
        raise PolicyLoadError("Policy YAML must contain a top-level 'sops' list")

    try:
        policies = [SOP.model_validate(item) for item in data["sops"]]
    except ValidationError as exc:
        raise PolicyLoadError(f"Invalid SOP schema in {policy_path}: {exc}") from exc

    policy_ids = [policy.id for policy in policies]
    duplicate_ids = sorted({policy_id for policy_id in policy_ids if policy_ids.count(policy_id) > 1})
    if duplicate_ids:
        raise PolicyLoadError(f"Duplicate SOP IDs: {', '.join(duplicate_ids)}")

    return policies
