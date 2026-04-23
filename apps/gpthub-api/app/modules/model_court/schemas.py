from __future__ import annotations

from pydantic import BaseModel, Field


class ModelCourtCandidateResult(BaseModel):
    label: str = Field(min_length=1, max_length=8)
    model: str = Field(min_length=1, max_length=256)
    response: str = ""
    latency_ms: int = 0
    error: str = ""


class ModelCourtVerdict(BaseModel):
    winner_label: str = Field(min_length=1, max_length=8)
    winner_model: str = Field(min_length=1, max_length=256)
    final_answer: str
    rationale: str
    candidates: list[ModelCourtCandidateResult] = Field(default_factory=list)

