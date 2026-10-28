from pydantic import BaseModel, ConfigDict


class PolicyVersionRecord(BaseModel):
    """Tracks policy versions applied during sanitation plan generation."""

    model_config = ConfigDict(extra="ignore")

    template_policy_version: str = "sanitation-template-policy-1"
    resource_policy_version: str = "resource-policy-1"
    duration_policy_version: str = "duration-policy-1"
    safety_policy_version: str = "sanitation-safety-policy-1"
    supervisor_policy_versions: dict[str, str] = {}
