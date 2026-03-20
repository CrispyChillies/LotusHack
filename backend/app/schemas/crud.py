from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: Optional[str] = None
    persona: Optional[str] = None
    voice_sample_s3_url: Optional[str] = None
    voice_status: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    persona: Optional[str] = None
    voice_sample_s3_url: Optional[str] = None
    voice_status: Optional[str] = None


class UserRead(BaseModel):
    id: UUID
    full_name: Optional[str]
    email: Optional[str]
    role: Optional[str]
    persona: Optional[str]
    voice_sample_s3_url: Optional[str]
    voice_status: Optional[str]
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class FamilyCreate(BaseModel):
    patient_id: UUID
    name: str


class FamilyUpdate(BaseModel):
    patient_id: Optional[UUID] = None
    name: Optional[str] = None


class FamilyRead(BaseModel):
    id: UUID
    patient_id: Optional[UUID]
    name: Optional[str]
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class UserRelationCreate(BaseModel):
    subject_user_id: UUID
    object_user_id: UUID
    relation_name: str
    family_id: Optional[UUID] = None


class UserRelationUpdate(BaseModel):
    subject_user_id: Optional[UUID] = None
    object_user_id: Optional[UUID] = None
    relation_name: Optional[str] = None
    family_id: Optional[UUID] = None


class UserRelationRead(BaseModel):
    id: UUID
    subject_user_id: Optional[UUID]
    object_user_id: Optional[UUID]
    relation_name: Optional[str]
    family_id: Optional[UUID]

    model_config = ConfigDict(from_attributes=True)


class MediaCreate(BaseModel):
    family_id: UUID
    uploaded_by: UUID
    s3_url: str
    media_type: str
    captured_at: Optional[datetime] = None
    ai_summary: Optional[str] = None


class MediaUpdate(BaseModel):
    family_id: Optional[UUID] = None
    uploaded_by: Optional[UUID] = None
    s3_url: Optional[str] = None
    media_type: Optional[str] = None
    captured_at: Optional[datetime] = None
    ai_summary: Optional[str] = None


class MediaRead(BaseModel):
    id: UUID
    family_id: Optional[UUID]
    uploaded_by: Optional[UUID]
    s3_url: Optional[str]
    media_type: Optional[str]
    captured_at: Optional[datetime]
    ai_summary: Optional[str]
    uploaded_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class MemoryCreate(BaseModel):
    family_id: UUID
    title: str
    ai_generated_story: Optional[str] = None
    date_of_memory: Optional[datetime] = None


class MemoryUpdate(BaseModel):
    family_id: Optional[UUID] = None
    title: Optional[str] = None
    ai_generated_story: Optional[str] = None
    date_of_memory: Optional[datetime] = None


class MemoryRead(BaseModel):
    id: UUID
    family_id: Optional[UUID]
    title: Optional[str]
    ai_generated_story: Optional[str]
    date_of_memory: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ReminderCreate(BaseModel):
    patient_id: UUID
    related_user_id: Optional[UUID] = None
    title: str
    reminder_context: Optional[str] = None
    trigger_time: datetime
    is_active: bool = True
    generated_audio_s3_url: Optional[str] = None


class ReminderUpdate(BaseModel):
    patient_id: Optional[UUID] = None
    related_user_id: Optional[UUID] = None
    title: Optional[str] = None
    reminder_context: Optional[str] = None
    trigger_time: Optional[datetime] = None
    is_active: Optional[bool] = None
    generated_audio_s3_url: Optional[str] = None


class ReminderRead(BaseModel):
    id: UUID
    patient_id: Optional[UUID]
    related_user_id: Optional[UUID]
    title: Optional[str]
    reminder_context: Optional[str]
    trigger_time: Optional[datetime]
    is_active: Optional[bool]
    generated_audio_s3_url: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class MemoryStoryAudioCreate(BaseModel):
    memory_id: UUID
    speaker_user_id: UUID
    audio_s3_url: str
    duration: Optional[int] = None
    status: Optional[str] = None


class MemoryStoryAudioUpdate(BaseModel):
    memory_id: Optional[UUID] = None
    speaker_user_id: Optional[UUID] = None
    audio_s3_url: Optional[str] = None
    duration: Optional[int] = None
    status: Optional[str] = None


class MemoryStoryAudioRead(BaseModel):
    id: UUID
    memory_id: Optional[UUID]
    speaker_user_id: Optional[UUID]
    audio_s3_url: Optional[str]
    duration: Optional[int]
    status: Optional[str]
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
