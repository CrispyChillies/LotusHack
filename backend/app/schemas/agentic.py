from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TinyfishSSETestRequest(BaseModel):
    url: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    timeout_seconds: int = Field(default=180, ge=30, le=600)


class TinyfishSSETestResponse(BaseModel):
    ok: bool
    event_count: int
    final_event: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class JourneySlide(BaseModel):
    slide_index: int
    source_type: str
    source_id: str
    title: str
    memory_text: str
    narration_text: str
    media_url: str | None = None
    media_kind: str | None = None
    score: float


class JourneyCreateRequest(BaseModel):
    family_id: UUID
    journey_goal: str = Field(min_length=1)
    context_url: str | None = None
    top_k_slides: int = Field(default=5, ge=1, le=20)
    subquery_count: int = Field(default=5, ge=2, le=12)


class JourneyCreateResponse(BaseModel):
    family_id: UUID
    journey_goal: str
    generated_subqueries: list[str]
    slides: list[JourneySlide]
    tinyfish_used: bool
    tinyfish_event_count: int
    generated_at: datetime


class NotificationCandidate(BaseModel):
    source_type: str
    source_id: str
    title: str
    message: str
    score: float
    suggested_action: str
    memory_preview: str
    media_url: str | None = None


class MeaningfulNotificationRequest(BaseModel):
    family_id: UUID
    context_url: str | None = None
    min_score: float = Field(default=0.72, ge=0.1, le=2.0)
    max_notifications: int = Field(default=3, ge=1, le=10)


class MeaningfulNotificationResponse(BaseModel):
    family_id: UUID
    should_notify: bool
    generated_queries: list[str]
    candidates: list[NotificationCandidate]
    tinyfish_used: bool
    tinyfish_event_count: int
    generated_at: datetime
