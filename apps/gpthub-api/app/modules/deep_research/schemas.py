from __future__ import annotations

from pydantic import BaseModel, Field


class DeepResearchSource(BaseModel):
    index: int = Field(ge=1)
    title: str = ""
    url: str
    snippet: str = ""
    content: str = ""


class DeepResearchResult(BaseModel):
    answer: str
    sources: list[DeepResearchSource]
