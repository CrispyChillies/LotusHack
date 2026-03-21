from __future__ import annotations

from fastapi import APIRouter

from app.schemas.agentic import (
    JourneyCreateRequest,
    JourneyCreateResponse,
    MeaningfulNotificationRequest,
    MeaningfulNotificationResponse,
    TinyfishSSETestRequest,
    TinyfishSSETestResponse,
)
from app.services.tinyfish_agent_service import agentic_memory_companion_service

router = APIRouter()

@router.post("/tinyfish/sse/test", response_model=TinyfishSSETestResponse)
async def tinyfish_sse_test(payload: TinyfishSSETestRequest):
    events = agentic_memory_companion_service.tinyfish.run_sse(
        url=payload.url,
        goal=payload.goal,
        timeout_seconds=payload.timeout_seconds,
    )
    final_event = events[-1] if events else None
    return TinyfishSSETestResponse(
        ok=True,
        event_count=len(events),
        final_event=final_event,
        events=events,
    )

@router.post("/journey/test", response_model=JourneyCreateResponse)
async def build_memory_journey(payload: JourneyCreateRequest):
    result = await agentic_memory_companion_service.build_journey(
        family_id=str(payload.family_id),
        journey_goal=payload.journey_goal,
        top_k_slides=payload.top_k_slides,
        subquery_count=payload.subquery_count,
        context_url=payload.context_url,
    )
    return JourneyCreateResponse(**result)

@router.post("/meaningful-notifications/test", response_model=MeaningfulNotificationResponse)
async def meaningful_notifications(payload: MeaningfulNotificationRequest):
    result = await agentic_memory_companion_service.meaningful_notifications(
        family_id=str(payload.family_id),
        min_score=payload.min_score,
        max_notifications=payload.max_notifications,
        context_url=payload.context_url,
    )
    return MeaningfulNotificationResponse(**result)
