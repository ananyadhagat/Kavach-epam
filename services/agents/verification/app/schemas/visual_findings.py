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
    cleanup_score: float | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=100)


class GeminiObservationSet(BaseModel):
    """Exact Gemini observation shape; intentionally stricter than legacy mock fixtures."""
    model_config = ConfigDict(extra="forbid")
    overflow: Observation
    scattered_waste: Observation
    path_obstructed: Observation


class GeminiVisualFindings(BaseModel):
    """Vision-only semantic score schema. It cannot make a verification decision."""
    model_config = ConfigDict(extra="forbid")
    before_observations: GeminiObservationSet
    after_observations: GeminiObservationSet
    visual_change: VisualChange
    limitations: list[str] = Field(default_factory=list)
    cleanup_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
