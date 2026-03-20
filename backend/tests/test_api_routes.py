from fastapi.testclient import TestClient

from app.main import app


def test_health_root():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert "message" in body
    assert "docs" in body
