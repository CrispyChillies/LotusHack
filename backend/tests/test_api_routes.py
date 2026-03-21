from fastapi.testclient import TestClient

from app.main import app
from app.routers import graph_router


def test_health_root():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert "message" in body
    assert "docs" in body


def test_graph_query_hybrid_endpoint(monkeypatch):
    async def fake_hybrid_search(**kwargs):
        class _Item:
            def __init__(self):
                self.source_type = "media"
                self.source_id = "11111111-1111-1111-1111-111111111111"
                self.content = "Anna and grandpa at park"
                self.vector_score = 0.9
                self.graph_score = 0.7
                self.final_score = 0.83
                self.metadata = {"source_type": "media"}

        return [_Item()]

    monkeypatch.setattr(graph_router.memory_graph_service, "hybrid_search", fake_hybrid_search)

    client = TestClient(app)
    response = client.post(
        "/api/v1/graph/query",
        json={
            "family_id": "11111111-1111-1111-1111-111111111111",
            "query": "grandpa and anna in park",
            "top_k": 5,
            "use_advanced": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid"
    assert len(body["results"]) == 1


def test_graph_query_advanced_endpoint(monkeypatch):
    async def fake_advanced_query(**kwargs):
        return {
            "results": [
                {
                    "source_type": "memory",
                    "source_id": "22222222-2222-2222-2222-222222222222",
                    "content": "Camping trip memory",
                    "vector_score": 0.85,
                    "graph_score": 0.78,
                    "final_score": 0.82,
                    "metadata": {},
                }
            ],
            "graph_context": {"nodes": [{"id": "n1"}], "edges": []},
        }

    monkeypatch.setattr(graph_router.memory_graph_service, "advanced_memory_query", fake_advanced_query)

    client = TestClient(app)
    response = client.post(
        "/api/v1/graph/query",
        json={
            "family_id": "11111111-1111-1111-1111-111111111111",
            "query": "camping",
            "top_k": 5,
            "use_advanced": True,
            "required_entities": ["Anna"],
            "required_relations": ["happened_at"],
            "max_hops": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "advanced"
    assert body["graph_context"] is not None


def test_frontend_page():
    client = TestClient(app)
    response = client.get("/frontend")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Memory Flow Manual Tester" in response.text


def test_graph_visualize_page():
    client = TestClient(app)
    response = client.get("/graph_visualize")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Memory Graph Visualizer" in response.text
