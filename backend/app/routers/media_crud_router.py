from datetime import datetime

from fastapi import APIRouter, File, Form, Response, UploadFile, status

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
    UploadedFileResponse,
)
from app.services import media_crud
from app.services import voice_service

router = APIRouter()


@router.post("/image/upload-url", response_model=UploadedFileResponse)
async def upload_image_file(file: UploadFile = File(...)):
    return await voice_service.upload_image_file(file)


@router.post("/voice/upload-url", response_model=UploadedFileResponse)
async def upload_voice_file(file: UploadFile = File(...)):
    return await voice_service.upload_voice_file(file)


@router.post("/media", response_model=MediaRead, status_code=201)
async def create_media(payload: MediaCreate):
    return await media_crud.create_media(payload)


@router.post("/media/upload", response_model=MediaRead, status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    family_id: str = Form(...),
    uploaded_by: str = Form(...),
    notes: str | None = Form(None),
    captured_at: datetime | None = Form(None),
):
    return await media_crud.create_media_with_upload(
        file=file,
        family_id=family_id,
        uploaded_by=uploaded_by,
        notes=notes,
        captured_at=captured_at,
    )


@router.get("/media/{media_id}", response_model=MediaRead)
async def get_media(media_id: str):
    return await media_crud.get_media(media_id)


@router.get("/media", response_model=list[MediaRead])
async def list_media(limit: int = 50, offset: int = 0):
    return await media_crud.list_media(limit=limit, offset=offset)


@router.patch("/media/{media_id}", response_model=MediaRead)
async def update_media(media_id: str, payload: MediaUpdate):
    return await media_crud.update_media(media_id, payload)


@router.delete("/media/{media_id}", status_code=204)
async def delete_media(media_id: str):
    await media_crud.delete_media(media_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/memories", response_model=MemoryRead, status_code=201)
async def create_memory(payload: MemoryCreate):
    return await media_crud.create_memory(payload)


@router.get("/memories/{memory_id}", response_model=MemoryRead)
async def get_memory(memory_id: str):
    return await media_crud.get_memory(memory_id)


@router.get("/memories", response_model=list[MemoryRead])
async def list_memories(limit: int = 50, offset: int = 0):
    return await media_crud.list_memories(limit=limit, offset=offset)


@router.patch("/memories/{memory_id}", response_model=MemoryRead)
async def update_memory(memory_id: str, payload: MemoryUpdate):
    return await media_crud.update_memory(memory_id, payload)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str):
    await media_crud.delete_memory(memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reminders", response_model=ReminderRead, status_code=201)
async def create_reminder(payload: ReminderCreate):
    return await media_crud.create_reminder(payload)


@router.get("/reminders/{reminder_id}", response_model=ReminderRead)
async def get_reminder(reminder_id: str):
    return await media_crud.get_reminder(reminder_id)


@router.get("/reminders", response_model=list[ReminderRead])
async def list_reminders(limit: int = 50, offset: int = 0):
    return await media_crud.list_reminders(limit=limit, offset=offset)


@router.patch("/reminders/{reminder_id}", response_model=ReminderRead)
async def update_reminder(reminder_id: str, payload: ReminderUpdate):
    return await media_crud.update_reminder(reminder_id, payload)


@router.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder(reminder_id: str):
    await media_crud.delete_reminder(reminder_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/memory-stories-audio", response_model=MemoryStoryAudioRead, status_code=201)
async def create_memory_story_audio(payload: MemoryStoryAudioCreate):
    return await media_crud.create_memory_story_audio(payload)


@router.get("/memory-stories-audio/{story_id}", response_model=MemoryStoryAudioRead)
async def get_memory_story_audio(story_id: str):
    return await media_crud.get_memory_story_audio(story_id)


@router.get("/memory-stories-audio", response_model=list[MemoryStoryAudioRead])
async def list_memory_stories_audio(limit: int = 50, offset: int = 0):
    return await media_crud.list_memory_stories_audio(limit=limit, offset=offset)


@router.patch("/memory-stories-audio/{story_id}", response_model=MemoryStoryAudioRead)
async def update_memory_story_audio(story_id: str, payload: MemoryStoryAudioUpdate):
    return await media_crud.update_memory_story_audio(story_id, payload)


@router.delete("/memory-stories-audio/{story_id}", status_code=204)
async def delete_memory_story_audio(story_id: str):
    await media_crud.delete_memory_story_audio(story_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
