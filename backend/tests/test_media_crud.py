import uuid

import pytest
from fastapi import HTTPException

from app.schemas.crud import MediaUpdate
from app.services import media_crud
from app.services.media_service import UploadMediaResult


class FakeCursor:
    def __init__(self, fetchone_values=None, rowcount=1):
        self.fetchone_values = list(fetchone_values or [])
        self.rowcount = rowcount
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if self.fetchone_values:
            return self.fetchone_values.pop(0)
        return None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_media_with_upload_success(monkeypatch):
    media_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    uploader_id = str(uuid.uuid4())

    cursor = FakeCursor(
        fetchone_values=[
            {
                "id": media_id,
                "family_id": family_id,
                "uploaded_by": uploader_id,
                "s3_url": "https://mem-s3-heheboy.s3.us-east-1.amazonaws.com/media/test.jpg",
                "media_type": "image",
                "captured_at": None,
                "notes": "birthday",
                "uploaded_at": None,
            }
        ]
    )

    async def fake_upload_media(upload, family_id):
        return UploadMediaResult(
            s3_key="media/test.jpg",
            s3_url="https://mem-s3-heheboy.s3.us-east-1.amazonaws.com/media/test.jpg",
            media_type="image",
            content_type="image/jpeg",
            size_bytes=10,
        )

    class FakeUpload:
        filename = "test.jpg"

    monkeypatch.setattr(media_crud, "_init_db", lambda: None)
    monkeypatch.setattr(media_crud, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(media_crud, "upload_media", fake_upload_media)

    class FakeMemoryGraphService:
        async def sync_media_item(self, media_id: str):
            return {"processed": 1, "nodes": 2, "edges": 2, "documents": 1}

    monkeypatch.setattr(media_crud, "memory_graph_service", FakeMemoryGraphService())

    result = await media_crud.create_media_with_upload(
        file=FakeUpload(),
        family_id=family_id,
        uploaded_by=uploader_id,
        notes="birthday",
    )

    assert str(result.id) == media_id
    assert result.media_type == "image"
    assert result.notes == "birthday"


@pytest.mark.asyncio
async def test_update_media_without_fields_raises(monkeypatch):
    monkeypatch.setattr(media_crud, "_init_db", lambda: None)

    with pytest.raises(HTTPException) as exc:
        await media_crud.update_media(str(uuid.uuid4()), MediaUpdate())

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_media_with_upload_graph_sync_failure_raises(monkeypatch):
    media_id = str(uuid.uuid4())
    family_id = str(uuid.uuid4())
    uploader_id = str(uuid.uuid4())

    cursor = FakeCursor(
        fetchone_values=[
            {
                "id": media_id,
                "family_id": family_id,
                "uploaded_by": uploader_id,
                "s3_url": "https://mem-s3-heheboy.s3.us-east-1.amazonaws.com/media/test.jpg",
                "media_type": "image",
                "captured_at": None,
                "notes": "birthday",
                "uploaded_at": None,
            }
        ]
    )

    async def fake_upload_media(upload, family_id):
        return UploadMediaResult(
            s3_key="media/test.jpg",
            s3_url="https://mem-s3-heheboy.s3.us-east-1.amazonaws.com/media/test.jpg",
            media_type="image",
            content_type="image/jpeg",
            size_bytes=10,
        )

    class FakeUpload:
        filename = "test.jpg"

    class FailingMemoryGraphService:
        async def sync_media_item(self, media_id: str):
            raise RuntimeError("graph unavailable")

    monkeypatch.setattr(media_crud, "_init_db", lambda: None)
    monkeypatch.setattr(media_crud, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(media_crud, "upload_media", fake_upload_media)
    monkeypatch.setattr(media_crud, "memory_graph_service", FailingMemoryGraphService())

    with pytest.raises(HTTPException) as exc:
        await media_crud.create_media_with_upload(
            file=FakeUpload(),
            family_id=family_id,
            uploaded_by=uploader_id,
            notes="birthday",
        )

    assert exc.value.status_code == 500
    assert "memory graph extraction/upsert failed" in exc.value.detail


@pytest.mark.asyncio
async def test_delete_reminder_not_found(monkeypatch):
    cursor = FakeCursor(rowcount=0)
    monkeypatch.setattr(media_crud, "_init_db", lambda: None)
    monkeypatch.setattr(media_crud, "_connect", lambda: FakeConnection(cursor))

    with pytest.raises(HTTPException) as exc:
        await media_crud.delete_reminder(str(uuid.uuid4()))

    assert exc.value.status_code == 404
