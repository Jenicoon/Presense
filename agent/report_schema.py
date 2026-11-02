"""Versioned contracts for post-presentation review (no model imports)."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False)]
Probability = Annotated[Finite, Field(ge=0, le=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignalQuality(Contract):
    faceDetected: bool = False
    audioValid: bool = False


class SegmentAnalysis(Contract):
    modelVersion: str | None = Field(default=None, max_length=100)
    metricDefinitionVersion: str | None = Field(default=None, max_length=100)
    conceptDefinitionVersion: str | None = Field(default=None, max_length=100)
    segmentId: str = Field(min_length=1, max_length=100)
    startMs: int = Field(ge=0)
    endMs: int = Field(gt=0)
    stressScore: Probability
    predictionConfidence: Probability | None = None
    concepts: dict[str, Finite] = Field(default_factory=dict, max_length=7)
    audioFeatures: dict[str, Finite | str | bool] = Field(default_factory=dict, max_length=32)
    videoFeatures: dict[str, Finite | str | bool] = Field(default_factory=dict, max_length=32)
    quality: SignalQuality

    @model_validator(mode="after")
    def valid_window(self):
        if self.endMs <= self.startMs or self.endMs - self.startMs > 10_100:
            raise ValueError("A segment must cover a positive capture window of at most 10.1 seconds.")
        if any(len(k) > 80 for values in (self.concepts, self.audioFeatures, self.videoFeatures) for k in values):
            raise ValueError("Feature names must be at most 80 characters.")
        if any(isinstance(v, str) and len(v) > 120 for values in (self.audioFeatures, self.videoFeatures) for v in values.values()):
            raise ValueError("Feature labels must be at most 120 characters.")
        return self


class PracticeContext(Contract):
    sessionId: str = Field(min_length=1, max_length=100)
    practiceId: str = Field(min_length=1, max_length=100)


class ReviewRequest(Contract):
    sessionId: str = Field(min_length=1, max_length=100)
    durationMs: int = Field(gt=0, le=14_400_000)
    language: Literal["ko", "en"] = "ko"
    modelVersion: str | None = Field(default=None, max_length=100)
    metricDefinitionVersion: str = Field(default="session-analysis-v4", max_length=100)
    conceptDefinitionVersion: str | None = Field(default=None, max_length=100)
    source: Literal["live"] = "live"
    sceneLabel: str | None = Field(default=None, max_length=120)
    practiceContext: PracticeContext | None = None
    segments: list[SegmentAnalysis] = Field(min_length=0, max_length=7200)
    personalBaseline: Probability | None = None
    baselineSampleCount: int | None = Field(default=None, ge=3, le=100)
    baselineModelVersion: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def valid_session(self):
        for field in ("modelVersion", "metricDefinitionVersion", "conceptDefinitionVersion"):
            values = {getattr(row,field) for row in self.segments}
            specified = values - {None}
            if len(specified)>1 or (specified and None in values):
                raise ValueError("A session cannot mix model or metric definition versions")
            if specified:
                value=next(iter(specified))
                if field in self.model_fields_set and getattr(self,field)!=value:
                    raise ValueError("Session and window versions differ")
                setattr(self,field,value)
        from .model_contract import RAW_METRICS
        new_keys={key for _,key,_,_ in RAW_METRICS}
        if self.metricDefinitionVersion!="session-analysis-v5-exact7" and (any(new_keys.intersection(row.audioFeatures.keys()|row.videoFeatures.keys()) for row in self.segments) or (self.modelVersion or "").startswith("exact7-v2-")):
            raise ValueError("New measurements cannot use legacy definitions")
        if self.metricDefinitionVersion=="session-analysis-v5-exact7":
            if not self.modelVersion or not self.modelVersion.startswith("exact7-v2-") or self.conceptDefinitionVersion!="literature-exact7-v2":
                raise ValueError("V2 measurements require their paired model and concept definition versions")
            from ai.concept_registry import PROPOSED_CONCEPTS_V2
            names={c.model_name_ko for c in PROPOSED_CONCEPTS_V2}
            if any(not set(row.concepts).issubset(names) for row in self.segments):
                raise ValueError("Legacy concept names cannot label V2 predictions")
        ids = [s.segmentId for s in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("Segment IDs must be unique.")
        if any(s.endMs > self.durationMs for s in self.segments):
            raise ValueError("Capture windows must fall inside the presentation.")
        baseline_fields = (self.personalBaseline, self.baselineSampleCount, self.baselineModelVersion)
        if any(value is not None for value in baseline_fields) and not all(value is not None for value in baseline_fields):
            raise ValueError("Personal baseline, sample count, and model version must be provided together.")
        return self


class Evidence(Contract):
    id: str
    source: str
    page: int | None = None
    chunk: int
    text: str
    distance: Finite
    title: str | None = None
    articleUrl: str | None = None
    doi: str | None = None
    scope: str | None = None
    findingKo: str | None = None
    topics: list[str] = Field(default_factory=list)
    evidenceRole: Literal["measurement", "practice_general", "practice_specific"] = "measurement"
    applicability: Literal["direct", "related"] = "related"


class CoachingItem(Contract):
    issueId: str
    researchBasis: str = Field(default="", max_length=600)
    recommendation: str = Field(min_length=1, max_length=900)
    evidenceIds: list[str] = Field(default_factory=list, max_length=3)


class Synthesis(Contract):
    summary: str = Field(min_length=1, max_length=1400)
    coaching: list[CoachingItem] = Field(default_factory=list, max_length=5)
