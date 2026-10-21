from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class Observation(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNCERTAIN = "UNCERTAIN"


class VisualChange(str, Enum):
    IMPROVED = "IMPROVED"
    NO_CHANGE = "NO_CHANGE"
    WORSE = "WORSE"
    UNCERTAIN = "UNCERTAIN"


class VisualFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before_observations: dict[str, Observation]
    after_observations: dict[str, Observation]
    visual_change: VisualChange
    limitations: list[str] = Field(default_factory=list)


class GeminiObservationSet(BaseModel):
    """Exact Gemini observation shape; intentionally stricter than legacy mock fixtures."""
    model_config = ConfigDict(extra="forbid")
    overflow: Observation
    scattered_waste: Observation
    path_obstructed: Observation


class GeminiVisualFindings(BaseModel):
    """Vision-only response schema. No decision, score, or remark fields are allowed."""
    model_config = ConfigDict(extra="forbid")
    before_observations: GeminiObservationSet
    after_observations: GeminiObservationSet
    visual_change: VisualChange
    limitations: list[str] = Field(default_factory=list)
