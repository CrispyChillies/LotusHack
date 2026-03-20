import uuid

import pytest
from fastapi import HTTPException

from app.schemas.crud import UserCreate, UserUpdate
from app.services import user_crud


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
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_user_success(monkeypatch):
    created_id = str(uuid.uuid4())
    cursor = FakeCursor(
        fetchone_values=[
            None,
            {
                "id": created_id,
                "full_name": "Alice",
                "email": "alice@example.com",
                "role": "patient",
                "persona": "calm",
                "voice_sample_s3_url": None,
                "voice_status": None,
                "created_at": None,
            },
        ]
    )

    monkeypatch.setattr(user_crud, "_init_db", lambda: None)
    monkeypatch.setattr(user_crud, "_connect", lambda: FakeConnection(cursor))

    result = await user_crud.create_user(
        UserCreate(
            email="alice@example.com",
            full_name="Alice",
            role="patient",
            persona="calm",
        )
    )

    assert result.email == "alice@example.com"
    assert str(result.id) == created_id
    assert len(cursor.executed) == 2


@pytest.mark.asyncio
async def test_update_user_without_fields_raises(monkeypatch):
    monkeypatch.setattr(user_crud, "_init_db", lambda: None)

    with pytest.raises(HTTPException) as exc:
        await user_crud.update_user(str(uuid.uuid4()), UserUpdate())

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_user_not_found(monkeypatch):
    cursor = FakeCursor(rowcount=0)
    monkeypatch.setattr(user_crud, "_init_db", lambda: None)
    monkeypatch.setattr(user_crud, "_connect", lambda: FakeConnection(cursor))

    with pytest.raises(HTTPException) as exc:
        await user_crud.delete_user(str(uuid.uuid4()))

    assert exc.value.status_code == 404
