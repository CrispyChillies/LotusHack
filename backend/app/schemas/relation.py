from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class JoinByQRRequest(BaseModel):
    qr_token: str
    create_transitive: bool = True


class RelationEdge(BaseModel):
    subject_user_id: UUID
    object_user_id: UUID
    relation_name: str
    family_id: UUID
    source: str


class JoinByQRResponse(BaseModel):
    family_id: UUID
    patient_id: UUID
    new_user_id: UUID
    created: list[RelationEdge]
    skipped: list[RelationEdge]
