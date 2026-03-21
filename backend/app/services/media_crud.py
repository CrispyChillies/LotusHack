from __future__ import annotations

import os
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile, status
from psycopg.rows import dict_row

from app.schemas.crud import (
	MediaCreate,
	MediaRead,
	MediaUpdate,
	MemoryCreate,
	MemoryRead,
	MemoryStoryAudioCreate,
	MemoryStoryAudioRead,
	MemoryStoryAudioUpdate,
	MemoryUpdate,
	ReminderCreate,
	ReminderRead,
	ReminderUpdate,
)
from app.services.memory_graph_service import memory_graph_service
from app.services.media_service import upload_media

load_dotenv()


def _get_env(name: str) -> str:
	value = os.getenv(name)
	if not value:
		raise RuntimeError(f"Missing required environment variable: {name}")
	return value


def _connect() -> psycopg.Connection:
	return psycopg.connect(_get_env("DATABASE_URL"), row_factory=dict_row)


@lru_cache(maxsize=1)
def _init_db() -> None:
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				CREATE TABLE IF NOT EXISTS media (
					id UUID PRIMARY KEY,
					family_id UUID REFERENCES families(id) ON DELETE CASCADE,
					uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL,
					s3_url VARCHAR,
					media_type VARCHAR,
					captured_at TIMESTAMPTZ,
					notes TEXT,
					uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
				)
				"""
			)
			cur.execute("ALTER TABLE media ADD COLUMN IF NOT EXISTS notes TEXT")
			cur.execute(
				"""
				DO $$
				BEGIN
					IF EXISTS (
						SELECT 1
						FROM information_schema.columns
						WHERE table_name = 'media' AND column_name = 'ai_summary'
					) THEN
						EXECUTE 'UPDATE media SET notes = COALESCE(notes, ai_summary)';
					END IF;
				END $$;
				"""
			)
			cur.execute(
				"""
				CREATE TABLE IF NOT EXISTS memories (
					id UUID PRIMARY KEY,
					family_id UUID REFERENCES families(id) ON DELETE CASCADE,
					title VARCHAR,
					ai_generated_story TEXT,
					date_of_memory TIMESTAMPTZ
				)
				"""
			)
			cur.execute(
				"""
				CREATE TABLE IF NOT EXISTS reminders (
					id UUID PRIMARY KEY,
					patient_id UUID REFERENCES users(id) ON DELETE CASCADE,
					related_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
					title VARCHAR,
					reminder_context TEXT,
					trigger_time TIMESTAMPTZ,
					is_active BOOLEAN,
					generated_audio_s3_url VARCHAR
				)
				"""
			)
			cur.execute(
				"""
				CREATE TABLE IF NOT EXISTS memory_stories_audio (
					id UUID PRIMARY KEY,
					memory_id UUID REFERENCES memories(id) ON DELETE CASCADE,
					speaker_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
					audio_s3_url VARCHAR,
					duration INTEGER,
					status VARCHAR,
					created_at TIMESTAMPTZ NOT NULL DEFAULT now()
				)
				"""
			)
		conn.commit()


def _build_update_clause(values: dict[str, Any]) -> tuple[str, list[Any]]:
	if not values:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="No fields to update.",
		)
	assignments = []
	params: list[Any] = []
	for column, value in values.items():
		assignments.append(f"{column} = %s")
		params.append(value)
	return ", ".join(assignments), params


def _as_uuid(value: str, field_name: str) -> str:
	try:
		return str(UUID(value))
	except ValueError:
		raise HTTPException(status_code=400, detail=f"Invalid {field_name}.")


def _raise_not_found(resource: str, resource_id: str) -> None:
	raise HTTPException(status_code=404, detail=f"{resource} not found: {resource_id}")


async def create_media(payload: MediaCreate) -> MediaRead:
	_init_db()
	media_id = uuid4()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO media (id, family_id, uploaded_by, s3_url, media_type, captured_at, notes, uploaded_at)
				VALUES (%s, %s, %s, %s, %s, %s, %s, now())
				RETURNING id, family_id, uploaded_by, s3_url, media_type, captured_at, notes, uploaded_at
				""",
				(
					str(media_id),
					str(payload.family_id),
					str(payload.uploaded_by),
					payload.s3_url,
					payload.media_type,
					payload.captured_at,
					payload.notes,
				),
			)
			row = cur.fetchone()
		conn.commit()
	return MediaRead(**row)


async def create_media_with_upload(
	file: UploadFile,
	family_id: str,
	uploaded_by: str,
	captured_at: Any = None,
	notes: str | None = None,
) -> MediaRead:
	_init_db()
	family_uuid = _as_uuid(family_id, "family id")
	uploader_uuid = _as_uuid(uploaded_by, "uploaded_by")

	upload_result = await upload_media(upload=file, family_id=family_uuid)
	created_media = await create_media(
		MediaCreate(
			family_id=UUID(family_uuid),
			uploaded_by=UUID(uploader_uuid),
			s3_url=upload_result.s3_url,
			media_type=upload_result.media_type,
			captured_at=captured_at,
			notes=notes,
		)
	)

	try:
		await memory_graph_service.sync_media_item(str(created_media.id))
	except HTTPException:
		raise
	except Exception as exc:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=(
				"Media uploaded and saved, but memory graph extraction/upsert failed: "
				f"{exc}"
			),
		)

	return created_media


async def get_media(media_id: str) -> MediaRead:
	_init_db()
	media_uuid = _as_uuid(media_id, "media id")
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, family_id, uploaded_by, s3_url, media_type, captured_at, notes, uploaded_at
				FROM media
				WHERE id = %s
				""",
				(media_uuid,),
			)
			row = cur.fetchone()
	if not row:
		_raise_not_found("Media", media_id)
	return MediaRead(**row)


async def list_media(limit: int = 50, offset: int = 0) -> list[MediaRead]:
	_init_db()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, family_id, uploaded_by, s3_url, media_type, captured_at, notes, uploaded_at
				FROM media
				ORDER BY uploaded_at DESC
				LIMIT %s OFFSET %s
				""",
				(max(1, min(limit, 200)), max(offset, 0)),
			)
			rows = cur.fetchall()
	return [MediaRead(**row) for row in rows]


async def update_media(media_id: str, payload: MediaUpdate) -> MediaRead:
	_init_db()
	media_uuid = _as_uuid(media_id, "media id")

	values = payload.model_dump(exclude_none=True)
	for field in ("family_id", "uploaded_by"):
		if field in values:
			values[field] = str(values[field])
	set_clause, params = _build_update_clause(values)
	params.append(media_uuid)

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				f"""
				UPDATE media
				SET {set_clause}
				WHERE id = %s
				RETURNING id, family_id, uploaded_by, s3_url, media_type, captured_at, notes, uploaded_at
				""",
				params,
			)
			row = cur.fetchone()
		conn.commit()
	if not row:
		_raise_not_found("Media", media_id)
	return MediaRead(**row)


async def delete_media(media_id: str) -> None:
	_init_db()
	media_uuid = _as_uuid(media_id, "media id")
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute("DELETE FROM media WHERE id = %s", (media_uuid,))
			deleted = cur.rowcount
		conn.commit()
	if deleted == 0:
		_raise_not_found("Media", media_id)


async def create_memory(payload: MemoryCreate) -> MemoryRead:
	_init_db()
	memory_id = uuid4()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO memories (id, family_id, title, ai_generated_story, date_of_memory)
				VALUES (%s, %s, %s, %s, %s)
				RETURNING id, family_id, title, ai_generated_story, date_of_memory
				""",
				(
					str(memory_id),
					str(payload.family_id),
					payload.title,
					payload.ai_generated_story,
					payload.date_of_memory,
				),
			)
			row = cur.fetchone()
		conn.commit()
	return MemoryRead(**row)


async def get_memory(memory_id: str) -> MemoryRead:
	_init_db()
	memory_uuid = _as_uuid(memory_id, "memory id")
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"SELECT id, family_id, title, ai_generated_story, date_of_memory FROM memories WHERE id = %s",
				(memory_uuid,),
			)
			row = cur.fetchone()
	if not row:
		_raise_not_found("Memory", memory_id)
	return MemoryRead(**row)


async def list_memories(limit: int = 50, offset: int = 0) -> list[MemoryRead]:
	_init_db()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, family_id, title, ai_generated_story, date_of_memory
				FROM memories
				ORDER BY date_of_memory DESC NULLS LAST, id ASC
				LIMIT %s OFFSET %s
				""",
				(max(1, min(limit, 200)), max(offset, 0)),
			)
			rows = cur.fetchall()
	return [MemoryRead(**row) for row in rows]


async def update_memory(memory_id: str, payload: MemoryUpdate) -> MemoryRead:
	_init_db()
	memory_uuid = _as_uuid(memory_id, "memory id")
	values = payload.model_dump(exclude_none=True)
	if "family_id" in values:
		values["family_id"] = str(values["family_id"])
	set_clause, params = _build_update_clause(values)
	params.append(memory_uuid)

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				f"""
				UPDATE memories
				SET {set_clause}
				WHERE id = %s
				RETURNING id, family_id, title, ai_generated_story, date_of_memory
				""",
				params,
			)
			row = cur.fetchone()
		conn.commit()
	if not row:
		_raise_not_found("Memory", memory_id)
	return MemoryRead(**row)


async def delete_memory(memory_id: str) -> None:
	_init_db()
	memory_uuid = _as_uuid(memory_id, "memory id")
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute("DELETE FROM memories WHERE id = %s", (memory_uuid,))
			deleted = cur.rowcount
		conn.commit()
	if deleted == 0:
		_raise_not_found("Memory", memory_id)


async def create_reminder(payload: ReminderCreate) -> ReminderRead:
	_init_db()
	reminder_id = uuid4()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO reminders (
					id, patient_id, related_user_id, title, reminder_context,
					trigger_time, is_active, generated_audio_s3_url
				)
				VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
				RETURNING id, patient_id, related_user_id, title, reminder_context, trigger_time, is_active, generated_audio_s3_url
				""",
				(
					str(reminder_id),
					str(payload.patient_id),
					str(payload.related_user_id) if payload.related_user_id else None,
					payload.title,
					payload.reminder_context,
					payload.trigger_time,
					payload.is_active,
					payload.generated_audio_s3_url,
				),
			)
			row = cur.fetchone()
		conn.commit()
	return ReminderRead(**row)


async def get_reminder(reminder_id: str) -> ReminderRead:
	_init_db()
	reminder_uuid = _as_uuid(reminder_id, "reminder id")
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, patient_id, related_user_id, title, reminder_context, trigger_time, is_active, generated_audio_s3_url
				FROM reminders
				WHERE id = %s
				""",
				(reminder_uuid,),
			)
			row = cur.fetchone()
	if not row:
		_raise_not_found("Reminder", reminder_id)
	return ReminderRead(**row)


async def list_reminders(limit: int = 50, offset: int = 0) -> list[ReminderRead]:
	_init_db()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, patient_id, related_user_id, title, reminder_context, trigger_time, is_active, generated_audio_s3_url
				FROM reminders
				ORDER BY trigger_time ASC
				LIMIT %s OFFSET %s
				""",
				(max(1, min(limit, 200)), max(offset, 0)),
			)
			rows = cur.fetchall()
	return [ReminderRead(**row) for row in rows]


async def update_reminder(reminder_id: str, payload: ReminderUpdate) -> ReminderRead:
	_init_db()
	reminder_uuid = _as_uuid(reminder_id, "reminder id")
	values = payload.model_dump(exclude_none=True)
	for field in ("patient_id", "related_user_id"):
		if field in values and values[field] is not None:
			values[field] = str(values[field])
	set_clause, params = _build_update_clause(values)
	params.append(reminder_uuid)

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				f"""
				UPDATE reminders
				SET {set_clause}
				WHERE id = %s
				RETURNING id, patient_id, related_user_id, title, reminder_context, trigger_time, is_active, generated_audio_s3_url
				""",
				params,
			)
			row = cur.fetchone()
		conn.commit()
	if not row:
		_raise_not_found("Reminder", reminder_id)
	return ReminderRead(**row)


async def delete_reminder(reminder_id: str) -> None:
	_init_db()
	reminder_uuid = _as_uuid(reminder_id, "reminder id")
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute("DELETE FROM reminders WHERE id = %s", (reminder_uuid,))
			deleted = cur.rowcount
		conn.commit()
	if deleted == 0:
		_raise_not_found("Reminder", reminder_id)


async def create_memory_story_audio(payload: MemoryStoryAudioCreate) -> MemoryStoryAudioRead:
	_init_db()
	story_id = uuid4()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO memory_stories_audio (id, memory_id, speaker_user_id, audio_s3_url, duration, status, created_at)
				VALUES (%s, %s, %s, %s, %s, %s, now())
				RETURNING id, memory_id, speaker_user_id, audio_s3_url, duration, status, created_at
				""",
				(
					str(story_id),
					str(payload.memory_id),
					str(payload.speaker_user_id),
					payload.audio_s3_url,
					payload.duration,
					payload.status,
				),
			)
			row = cur.fetchone()
		conn.commit()
	return MemoryStoryAudioRead(**row)


async def get_memory_story_audio(story_id: str) -> MemoryStoryAudioRead:
	_init_db()
	story_uuid = _as_uuid(story_id, "memory story audio id")
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, memory_id, speaker_user_id, audio_s3_url, duration, status, created_at
				FROM memory_stories_audio
				WHERE id = %s
				""",
				(story_uuid,),
			)
			row = cur.fetchone()
	if not row:
		_raise_not_found("Memory story audio", story_id)
	return MemoryStoryAudioRead(**row)


async def list_memory_stories_audio(limit: int = 50, offset: int = 0) -> list[MemoryStoryAudioRead]:
	_init_db()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, memory_id, speaker_user_id, audio_s3_url, duration, status, created_at
				FROM memory_stories_audio
				ORDER BY created_at DESC
				LIMIT %s OFFSET %s
				""",
				(max(1, min(limit, 200)), max(offset, 0)),
			)
			rows = cur.fetchall()
	return [MemoryStoryAudioRead(**row) for row in rows]


async def update_memory_story_audio(story_id: str, payload: MemoryStoryAudioUpdate) -> MemoryStoryAudioRead:
	_init_db()
	story_uuid = _as_uuid(story_id, "memory story audio id")

	values = payload.model_dump(exclude_none=True)
	for field in ("memory_id", "speaker_user_id"):
		if field in values:
			values[field] = str(values[field])
	set_clause, params = _build_update_clause(values)
	params.append(story_uuid)

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				f"""
				UPDATE memory_stories_audio
				SET {set_clause}
				WHERE id = %s
				RETURNING id, memory_id, speaker_user_id, audio_s3_url, duration, status, created_at
				""",
				params,
			)
			row = cur.fetchone()
		conn.commit()
	if not row:
		_raise_not_found("Memory story audio", story_id)
	return MemoryStoryAudioRead(**row)


async def delete_memory_story_audio(story_id: str) -> None:
	_init_db()
	story_uuid = _as_uuid(story_id, "memory story audio id")
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute("DELETE FROM memory_stories_audio WHERE id = %s", (story_uuid,))
			deleted = cur.rowcount
		conn.commit()
	if deleted == 0:
		_raise_not_found("Memory story audio", story_id)
