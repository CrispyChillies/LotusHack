from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

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


class GraphQueryRequest(BaseModel):
    family_id: UUID
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    node_types: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    use_advanced: bool = False
    required_entities: list[str] = Field(default_factory=list)
    required_relations: list[str] = Field(default_factory=list)
    max_hops: int = Field(default=2, ge=1, le=4)


class GraphQueryResponse(BaseModel):
    mode: str
    query: str
    family_id: UUID
    results: list[dict[str, Any]]
    graph_context: dict[str, Any] | None = None
