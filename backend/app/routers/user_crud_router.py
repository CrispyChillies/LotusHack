from fastapi import APIRouter, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.schemas.crud import (
    FamilyCreate,
    FamilyIdRead,
    FamilyRead,
    FamilyUpdate,
    VoiceUploadAndCloneResponse,
    UserCreate,
    UserRead,
    UserRelationCreate,
    UserRelationRead,
    UserRelationUpdate,
    UserVoiceUpdateRequest,
    UserUpdate,
    VoiceCloneResponse,
    VoiceSpeakRequest,
)
from app.services import user_crud
from app.services import voice_service

router = APIRouter()


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(payload: UserCreate):
    return await user_crud.create_user(payload)


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(user_id: str):
    return await user_crud.get_user(user_id)


@router.get("/users", response_model=list[UserRead])
async def list_users(limit: int = 50, offset: int = 0):
    return await user_crud.list_users(limit=limit, offset=offset)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(user_id: str, payload: UserUpdate):
    return await user_crud.update_user(user_id, payload)


@router.patch("/users/{user_id}/voice", response_model=UserRead)
async def update_user_voice(user_id: str, payload: UserVoiceUpdateRequest):
    return await voice_service.update_user_voice_sample(user_id, payload)


@router.post("/users/{user_id}/voice/clone", response_model=VoiceCloneResponse)
async def clone_user_voice(user_id: str):
    return await voice_service.clone_user_voice(user_id)


@router.post("/users/{user_id}/voice/upload-and-clone", response_model=VoiceUploadAndCloneResponse)
async def upload_and_clone_user_voice(user_id: str, file: UploadFile):
    return await voice_service.upload_and_clone_user_voice(user_id, file)


@router.post("/users/{user_id}/voice/speak")
async def speak_with_user_voice(user_id: str, payload: VoiceSpeakRequest):
    tts_audio = await voice_service.speak_with_user_voice(user_id, payload)
    return StreamingResponse(
        content=iter([tts_audio.audio_bytes]),
        media_type=tts_audio.content_type,
        headers={"Content-Disposition": 'inline; filename="tts.mp3"'},
    )


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str):
    await user_crud.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/families", response_model=FamilyRead, status_code=201)
async def create_family(payload: FamilyCreate):
    return await user_crud.create_family(payload)


@router.get("/families/{family_id}", response_model=FamilyRead)
async def get_family(family_id: str):
    return await user_crud.get_family(family_id)


@router.get("/families", response_model=list[FamilyRead])
async def list_families(limit: int = 50, offset: int = 0):
    return await user_crud.list_families(limit=limit, offset=offset)


@router.get("/families/get_families_id/{user_id}", response_model=list[FamilyIdRead])
async def get_families_id(user_id: str):
    return await user_crud.get_families_id(user_id)


@router.patch("/families/{family_id}", response_model=FamilyRead)
async def update_family(family_id: str, payload: FamilyUpdate):
    return await user_crud.update_family(family_id, payload)


@router.delete("/families/{family_id}", status_code=204)
async def delete_family(family_id: str):
    await user_crud.delete_family(family_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/user-relations", response_model=UserRelationRead, status_code=201)
async def create_user_relation(payload: UserRelationCreate):
    return await user_crud.create_user_relation(payload)


@router.get("/user-relations/{relation_id}", response_model=UserRelationRead)
async def get_user_relation(relation_id: str):
    return await user_crud.get_user_relation(relation_id)


@router.get("/user-relations", response_model=list[UserRelationRead])
async def list_user_relations(limit: int = 50, offset: int = 0):
    return await user_crud.list_user_relations(limit=limit, offset=offset)


@router.patch("/user-relations/{relation_id}", response_model=UserRelationRead)
async def update_user_relation(relation_id: str, payload: UserRelationUpdate):
    return await user_crud.update_user_relation(relation_id, payload)


@router.delete("/user-relations/{relation_id}", status_code=204)
async def delete_user_relation(relation_id: str):
    await user_crud.delete_user_relation(relation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
