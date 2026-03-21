from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.routers import agentic_router


def test_tinyfish_sse_test_endpoint(monkeypatch):
    def fake_run_sse(*, url: str, goal: str, timeout_seconds: int = 180):
        assert url == "https://example.com"
        assert "extract" in goal.lower()
        assert timeout_seconds == 120
        return [{"status": "RUNNING"}, {"status": "COMPLETED", "resultJson": ["q1", "q2"]}]

    monkeypatch.setattr(agentic_router.agentic_memory_companion_service.tinyfish, "run_sse", fake_run_sse)

    client = TestClient(app)
    response = client.post(
        "/api/v1/agentic/tinyfish/sse/test",
        json={
            "url": "https://example.com",
            "goal": "extract memory hints",
            "timeout_seconds": 120,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["event_count"] == 2
    assert body["final_event"]["status"] == "COMPLETED"


def test_build_memory_journey_endpoint(monkeypatch):
    async def fake_build_journey(**kwargs):
        assert kwargs["family_id"] == "11111111-1111-1111-1111-111111111111"
        return {
            "family_id": kwargs["family_id"],
            "journey_goal": kwargs["journey_goal"],
            "generated_subqueries": ["q1", "q2"],
            "slides": [
                {
                    "slide_index": 1,
                    "source_type": "media",
                    "source_id": "a1",
                    "title": "Memory 1",
                    "memory_text": "Anna with grandpa",
                    "narration_text": "Let us revisit this memory.",
                    "media_url": "https://example.com/a.jpg",
                    "media_kind": "image",
                    "score": 0.91,
                }
            ],
            "tinyfish_used": True,
            "tinyfish_event_count": 4,
            "generated_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr(agentic_router.agentic_memory_companion_service, "build_journey", fake_build_journey)

    client = TestClient(app)
    response = client.post(
        "/api/v1/agentic/journey/test",
        json={
            "family_id": "11111111-1111-1111-1111-111111111111",
            "journey_goal": "grandpa birthday",
            "context_url": "https://example.com/family",
            "top_k_slides": 3,
            "subquery_count": 4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["journey_goal"] == "grandpa birthday"
    assert len(body["slides"]) == 1
    assert body["tinyfish_used"] is True


def test_meaningful_notifications_endpoint(monkeypatch):
    async def fake_notifications(**kwargs):
        return {
            "family_id": kwargs["family_id"],
            "should_notify": True,
            "generated_queries": ["family birthday memory"],
            "candidates": [
                {
                    "source_type": "memory",
                    "source_id": "m1",
                    "title": "Meaningful family memory",
                    "message": "A meaningful memory is ready.",
                    "score": 0.88,
                    "suggested_action": "Share this memory with family by call/video and replay the story.",
                    "memory_preview": "We celebrated together",
                    "media_url": None,
                }
            ],
            "tinyfish_used": False,
            "tinyfish_event_count": 0,
            "generated_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr(agentic_router.agentic_memory_companion_service, "meaningful_notifications", fake_notifications)

    client = TestClient(app)
    response = client.post(
        "/api/v1/agentic/meaningful-notifications/test",
        json={
            "family_id": "11111111-1111-1111-1111-111111111111",
            "min_score": 0.7,
            "max_notifications": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["should_notify"] is True
    assert len(body["candidates"]) == 1
