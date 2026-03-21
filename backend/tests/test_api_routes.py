from fastapi.testclient import TestClient

from app.main import app
from app.routers import graph_router
from app.routers import user_crud_router
from app.schemas.crud import UploadedFileResponse


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


def test_create_user_with_avatar_file(monkeypatch):
    captured = {}

    async def fake_upload_image_file(file):
        captured["filename"] = file.filename
        return UploadedFileResponse(
            s3_key="uploads/images/alice.png",
            s3_url="s3://bucket/uploads/images/alice.png",
            content_type="image/png",
            size_bytes=128,
        )

    async def fake_create_user(payload):
        captured["payload"] = payload
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "full_name": payload.full_name,
            "email": payload.email,
            "role": payload.role,
            "persona": payload.persona,
            "avatar_s3_url": payload.avatar_s3_url,
            "voice_sample_s3_url": payload.voice_sample_s3_url,
            "voice_status": payload.voice_status,
            "eleven_voice_id": payload.eleven_voice_id,
            "created_at": None,
        }

    monkeypatch.setattr(user_crud_router.voice_service, "upload_image_file", fake_upload_image_file)
    monkeypatch.setattr(user_crud_router.user_crud, "create_user", fake_create_user)

    client = TestClient(app)
    response = client.post(
        "/api/v1/users",
        data={
            "email": "alice@example.com",
            "full_name": "Alice",
            "role": "patient",
            "persona": "calm",
        },
        files={"avatar": ("alice.png", b"fakepng", "image/png")},
    )

    assert response.status_code == 201
    body = response.json()
    assert captured["filename"] == "alice.png"
    assert captured["payload"].avatar_s3_url == "s3://bucket/uploads/images/alice.png"
    assert body["avatar_s3_url"] == "s3://bucket/uploads/images/alice.png"


def test_update_user_with_avatar_file(monkeypatch):
    captured = {}

    async def fake_upload_image_file(file):
        captured["filename"] = file.filename
        return UploadedFileResponse(
            s3_key="uploads/images/avatar.png",
            s3_url="s3://bucket/uploads/images/avatar.png",
            content_type="image/png",
            size_bytes=256,
        )

    async def fake_update_user(user_id, payload):
        captured["user_id"] = user_id
        captured["payload"] = payload
        return {
            "id": user_id,
            "full_name": payload.full_name or "Alice",
            "email": "alice@example.com",
            "role": payload.role or "patient",
            "persona": payload.persona,
            "avatar_s3_url": payload.avatar_s3_url,
            "voice_sample_s3_url": payload.voice_sample_s3_url,
            "voice_status": payload.voice_status,
            "eleven_voice_id": payload.eleven_voice_id,
            "created_at": None,
        }

    monkeypatch.setattr(user_crud_router.voice_service, "upload_image_file", fake_upload_image_file)
    monkeypatch.setattr(user_crud_router.user_crud, "update_user", fake_update_user)

    client = TestClient(app)
    response = client.patch(
        "/api/v1/users/11111111-1111-1111-1111-111111111111",
        data={"full_name": "Alice Updated"},
        files={"avatar": ("avatar.png", b"fakepng", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert captured["filename"] == "avatar.png"
    assert captured["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert captured["payload"].avatar_s3_url == "s3://bucket/uploads/images/avatar.png"
    assert body["avatar_s3_url"] == "s3://bucket/uploads/images/avatar.png"


def test_upload_and_clone_user_voice_endpoint(monkeypatch):
    async def fake_upload_and_clone_user_voice(user_id: str, file):
        return {
            "upload": {
                "s3_key": "uploads/voices/sample.wav",
                "s3_url": "s3://bucket/uploads/voices/sample.wav",
                "content_type": "audio/wav",
                "size_bytes": 128,
            },
            "user": {
                "id": "11111111-1111-1111-1111-111111111111",
                "full_name": "Alice",
                "email": "alice@example.com",
                "role": "patient",
                "persona": None,
                "avatar_s3_url": None,
                "voice_sample_s3_url": "s3://bucket/uploads/voices/sample.wav",
                "voice_status": "ready",
                "eleven_voice_id": "voice_123",
                "created_at": None,
            },
            "clone": {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "voice_status": "ready",
                "eleven_voice_id": "voice_123",
            },
        }

    monkeypatch.setattr(user_crud_router.voice_service, "upload_and_clone_user_voice", fake_upload_and_clone_user_voice)

    client = TestClient(app)
    response = client.post(
        "/api/v1/users/11111111-1111-1111-1111-111111111111/voice/upload-and-clone",
        files={"file": ("sample.wav", b"RIFFfake", "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["upload"]["s3_url"].startswith("s3://")
    assert body["user"]["voice_sample_s3_url"] == body["upload"]["s3_url"]
    assert body["clone"]["eleven_voice_id"] == "voice_123"


def test_upload_user_avatar_endpoint(monkeypatch):
    async def fake_upload_image_file(file):
        return UploadedFileResponse(
            s3_key="uploads/images/avatar.png",
            s3_url="s3://bucket/uploads/images/avatar.png",
            content_type="image/png",
            size_bytes=256,
        )

    async def fake_update_user_avatar(user_id: str, avatar_s3_url: str | None):
        return {
            "id": user_id,
            "full_name": "Alice",
            "email": "alice@example.com",
            "role": "patient",
            "persona": None,
            "avatar_s3_url": avatar_s3_url,
            "voice_sample_s3_url": None,
            "voice_status": None,
            "eleven_voice_id": None,
            "created_at": None,
        }

    monkeypatch.setattr(user_crud_router.voice_service, "upload_image_file", fake_upload_image_file)
    monkeypatch.setattr(user_crud_router.user_crud, "update_user_avatar", fake_update_user_avatar)

    client = TestClient(app)
    response = client.post(
        "/api/v1/users/11111111-1111-1111-1111-111111111111/avatar/upload",
        files={"file": ("avatar.png", b"fakepng", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["upload"]["s3_url"] == "s3://bucket/uploads/images/avatar.png"
    assert body["user"]["avatar_s3_url"] == body["upload"]["s3_url"]
