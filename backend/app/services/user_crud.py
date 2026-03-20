from __future__ import annotations

import os
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import HTTPException, status
from psycopg.rows import dict_row

from app.schemas.crud import (
	FamilyCreate,
	FamilyRead,
	FamilyUpdate,
	UserCreate,
	UserRead,
	UserRelationCreate,
	UserRelationRead,
	UserRelationUpdate,
	UserUpdate,
)

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
				CREATE TABLE IF NOT EXISTS users (
					id UUID PRIMARY KEY,
					full_name VARCHAR,
					email VARCHAR UNIQUE,
					role VARCHAR,
					persona TEXT,
					voice_sample_s3_url VARCHAR,
					voice_status VARCHAR,
					created_at TIMESTAMPTZ NOT NULL DEFAULT now()
				)
				"""
			)
			cur.execute(
				"""
				CREATE TABLE IF NOT EXISTS families (
					id UUID PRIMARY KEY,
					patient_id UUID REFERENCES users(id) ON DELETE CASCADE,
					name VARCHAR,
					created_at TIMESTAMPTZ NOT NULL DEFAULT now()
				)
				"""
			)
			cur.execute(
				"""
				CREATE TABLE IF NOT EXISTS user_relations (
					id UUID PRIMARY KEY,
					subject_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
					object_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
					relation_name VARCHAR,
					family_id UUID REFERENCES families(id) ON DELETE SET NULL
				)
				"""
			)
		conn.commit()


def _raise_not_found(resource: str, resource_id: str) -> None:
	raise HTTPException(
		status_code=status.HTTP_404_NOT_FOUND,
		detail=f"{resource} not found: {resource_id}",
	)


def _build_update_clause(values: dict[str, Any]) -> tuple[str, list[Any]]:
	if not values:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="No fields to update.",
		)
	assignments = []
	params: list[Any] = []
	for index, (column, value) in enumerate(values.items(), start=1):
		assignments.append(f"{column} = %s")
		params.append(value)
	return ", ".join(assignments), params


async def create_user(payload: UserCreate) -> UserRead:
	_init_db()
	user_id = uuid4()
	try:
		with _connect() as conn:
			with conn.cursor() as cur:
				cur.execute("SELECT 1 FROM users WHERE LOWER(email) = LOWER(%s)", (payload.email,))
				if cur.fetchone():
					raise HTTPException(
						status_code=status.HTTP_409_CONFLICT,
						detail="Email already exists.",
					)

				cur.execute(
					"""
					INSERT INTO users (id, full_name, email, role, persona, voice_sample_s3_url, voice_status, created_at)
					VALUES (%s, %s, %s, %s, %s, %s, %s, now())
					RETURNING id, full_name, email, role, persona, voice_sample_s3_url, voice_status, created_at
					""",
					(
						str(user_id),
						payload.full_name,
						payload.email,
						payload.role,
						payload.persona,
						payload.voice_sample_s3_url,
						payload.voice_status,
					),
				)
				row = cur.fetchone()
			conn.commit()
	except HTTPException:
		raise
	except psycopg.Error as exc:
		raise HTTPException(status_code=500, detail=f"Failed to create user: {exc}")

	return UserRead(**row)


async def get_user(user_id: str) -> UserRead:
	_init_db()
	try:
		user_uuid = str(UUID(user_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid user id.")

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, full_name, email, role, persona, voice_sample_s3_url, voice_status, created_at
				FROM users
				WHERE id = %s
				""",
				(user_uuid,),
			)
			row = cur.fetchone()

	if not row:
		_raise_not_found("User", user_id)
	return UserRead(**row)


async def list_users(limit: int = 50, offset: int = 0) -> list[UserRead]:
	_init_db()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, full_name, email, role, persona, voice_sample_s3_url, voice_status, created_at
				FROM users
				ORDER BY created_at DESC
				LIMIT %s OFFSET %s
				""",
				(max(1, min(limit, 200)), max(offset, 0)),
			)
			rows = cur.fetchall()
	return [UserRead(**row) for row in rows]


async def update_user(user_id: str, payload: UserUpdate) -> UserRead:
	_init_db()
	try:
		user_uuid = str(UUID(user_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid user id.")

	values = payload.model_dump(exclude_none=True)
	set_clause, params = _build_update_clause(values)
	params.append(user_uuid)

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				f"""
				UPDATE users
				SET {set_clause}
				WHERE id = %s
				RETURNING id, full_name, email, role, persona, voice_sample_s3_url, voice_status, created_at
				""",
				params,
			)
			row = cur.fetchone()
		conn.commit()

	if not row:
		_raise_not_found("User", user_id)
	return UserRead(**row)


async def delete_user(user_id: str) -> None:
	_init_db()
	try:
		user_uuid = str(UUID(user_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid user id.")

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute("DELETE FROM users WHERE id = %s", (user_uuid,))
			deleted = cur.rowcount
		conn.commit()

	if deleted == 0:
		_raise_not_found("User", user_id)


async def create_family(payload: FamilyCreate) -> FamilyRead:
	_init_db()
	family_id = uuid4()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO families (id, patient_id, name, created_at)
				VALUES (%s, %s, %s, now())
				RETURNING id, patient_id, name, created_at
				""",
				(str(family_id), str(payload.patient_id), payload.name),
			)
			row = cur.fetchone()
		conn.commit()
	return FamilyRead(**row)


async def get_family(family_id: str) -> FamilyRead:
	_init_db()
	try:
		family_uuid = str(UUID(family_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid family id.")

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"SELECT id, patient_id, name, created_at FROM families WHERE id = %s",
				(family_uuid,),
			)
			row = cur.fetchone()
	if not row:
		_raise_not_found("Family", family_id)
	return FamilyRead(**row)


async def list_families(limit: int = 50, offset: int = 0) -> list[FamilyRead]:
	_init_db()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, patient_id, name, created_at
				FROM families
				ORDER BY created_at DESC
				LIMIT %s OFFSET %s
				""",
				(max(1, min(limit, 200)), max(offset, 0)),
			)
			rows = cur.fetchall()
	return [FamilyRead(**row) for row in rows]


async def update_family(family_id: str, payload: FamilyUpdate) -> FamilyRead:
	_init_db()
	try:
		family_uuid = str(UUID(family_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid family id.")

	values = payload.model_dump(exclude_none=True)
	if "patient_id" in values:
		values["patient_id"] = str(values["patient_id"])
	set_clause, params = _build_update_clause(values)
	params.append(family_uuid)

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				f"""
				UPDATE families
				SET {set_clause}
				WHERE id = %s
				RETURNING id, patient_id, name, created_at
				""",
				params,
			)
			row = cur.fetchone()
		conn.commit()

	if not row:
		_raise_not_found("Family", family_id)
	return FamilyRead(**row)


async def delete_family(family_id: str) -> None:
	_init_db()
	try:
		family_uuid = str(UUID(family_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid family id.")

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute("DELETE FROM families WHERE id = %s", (family_uuid,))
			deleted = cur.rowcount
		conn.commit()
	if deleted == 0:
		_raise_not_found("Family", family_id)


async def create_user_relation(payload: UserRelationCreate) -> UserRelationRead:
	_init_db()
	relation_id = uuid4()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				INSERT INTO user_relations (id, subject_user_id, object_user_id, relation_name, family_id)
				VALUES (%s, %s, %s, %s, %s)
				RETURNING id, subject_user_id, object_user_id, relation_name, family_id
				""",
				(
					str(relation_id),
					str(payload.subject_user_id),
					str(payload.object_user_id),
					payload.relation_name,
					str(payload.family_id) if payload.family_id else None,
				),
			)
			row = cur.fetchone()
		conn.commit()
	return UserRelationRead(**row)


async def get_user_relation(relation_id: str) -> UserRelationRead:
	_init_db()
	try:
		relation_uuid = str(UUID(relation_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid relation id.")

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, subject_user_id, object_user_id, relation_name, family_id
				FROM user_relations
				WHERE id = %s
				""",
				(relation_uuid,),
			)
			row = cur.fetchone()
	if not row:
		_raise_not_found("User relation", relation_id)
	return UserRelationRead(**row)


async def list_user_relations(limit: int = 50, offset: int = 0) -> list[UserRelationRead]:
	_init_db()
	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				"""
				SELECT id, subject_user_id, object_user_id, relation_name, family_id
				FROM user_relations
				ORDER BY relation_name ASC, id ASC
				LIMIT %s OFFSET %s
				""",
				(max(1, min(limit, 200)), max(offset, 0)),
			)
			rows = cur.fetchall()
	return [UserRelationRead(**row) for row in rows]


async def update_user_relation(relation_id: str, payload: UserRelationUpdate) -> UserRelationRead:
	_init_db()
	try:
		relation_uuid = str(UUID(relation_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid relation id.")

	values = payload.model_dump(exclude_none=True)
	for field in ("subject_user_id", "object_user_id", "family_id"):
		if field in values and values[field] is not None:
			values[field] = str(values[field])
	set_clause, params = _build_update_clause(values)
	params.append(relation_uuid)

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute(
				f"""
				UPDATE user_relations
				SET {set_clause}
				WHERE id = %s
				RETURNING id, subject_user_id, object_user_id, relation_name, family_id
				""",
				params,
			)
			row = cur.fetchone()
		conn.commit()

	if not row:
		_raise_not_found("User relation", relation_id)
	return UserRelationRead(**row)


async def delete_user_relation(relation_id: str) -> None:
	_init_db()
	try:
		relation_uuid = str(UUID(relation_id))
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid relation id.")

	with _connect() as conn:
		with conn.cursor() as cur:
			cur.execute("DELETE FROM user_relations WHERE id = %s", (relation_uuid,))
			deleted = cur.rowcount
		conn.commit()
	if deleted == 0:
		_raise_not_found("User relation", relation_id)
