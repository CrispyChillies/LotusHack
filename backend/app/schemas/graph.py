from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExtractPreviewRequest(BaseModel):
    note_text: str = Field(min_length=1)
    image_url: str | None = None
    existing_entities: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class ExtractPreviewResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    summary: str
    extracted_at: str
    model: str
    llm_error: str | None = None
    graphiti_payload: dict[str, Any]
