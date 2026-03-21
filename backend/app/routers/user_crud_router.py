from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.schemas.crud import (
    FamilyCreate,
    FamilyIdRead,
    FamilyRead,
    FamilyUpdate,
    UserAvatarUpdateRequest,
    UserAvatarUploadResponse,
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


def _normalize_form_value(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _parse_bool(value: object) -> bool | None:
    normalized = _normalize_form_value(value)
    if normalized is None:
        return None
    if isinstance(normalized, bool):
        return normalized
    if isinstance(normalized, str):
        lowered = normalized.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="remove_avatar must be a boolean value.",
    )


def _as_upload_file(value: object) -> UploadFile | None:
    if value is None:
        return None
    if hasattr(value, "filename") and hasattr(value, "read"):
        return value  # type: ignore[return-value]
    return None


def _validate_payload(model_cls, data: dict):
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


async def _parse_create_user_request(request: Request) -> tuple[UserCreate, UploadFile | None]:
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        return _validate_payload(UserCreate, await request.json()), None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload = _validate_payload(
            UserCreate,
            {
                field: _normalize_form_value(form[field])
                for field in (
                    "email",
                    "full_name",
                    "role",
                    "persona",
                    "avatar_s3_url",
                    "voice_sample_s3_url",
                    "voice_status",
                    "eleven_voice_id",
                )
                if field in form
            },
        )
        return payload, _as_upload_file(form.get("avatar"))

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Unsupported content type. Use application/json or multipart/form-data.",
    )


async def _parse_update_user_request(
    request: Request,
) -> tuple[UserUpdate, UploadFile | None, bool]:
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        return _validate_payload(UserUpdate, await request.json()), None, False

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload = _validate_payload(
            UserUpdate,
            {
                field: _normalize_form_value(form[field])
                for field in (
                    "full_name",
                    "role",
                    "persona",
                    "avatar_s3_url",
                    "voice_sample_s3_url",
                    "voice_status",
                    "eleven_voice_id",
                )
                if field in form
            },
        )
        remove_avatar = _parse_bool(form.get("remove_avatar")) or False
        return payload, _as_upload_file(form.get("avatar")), remove_avatar

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Unsupported content type. Use application/json or multipart/form-data.",
    )


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(request: Request):
    payload, avatar = await _parse_create_user_request(request)
    if avatar is not None:
        upload = await voice_service.upload_image_file(avatar)
        payload = payload.model_copy(update={"avatar_s3_url": upload.s3_url})
    return await user_crud.create_user(payload)


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(user_id: str):
    return await user_crud.get_user(user_id)


@router.get("/users", response_model=list[UserRead])
async def list_users(limit: int = 50, offset: int = 0):
    return await user_crud.list_users(limit=limit, offset=offset)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(user_id: str, request: Request):
    payload, avatar, remove_avatar = await _parse_update_user_request(request)
    updates = payload.model_dump(exclude_unset=True)

    if avatar is not None:
        upload = await voice_service.upload_image_file(avatar)
        updates["avatar_s3_url"] = upload.s3_url
    elif remove_avatar:
        updates["avatar_s3_url"] = None

    payload = UserUpdate.model_validate(updates)
    return await user_crud.update_user(user_id, payload)


@router.patch("/users/{user_id}/avatar", response_model=UserRead)
async def update_user_avatar(user_id: str, payload: UserAvatarUpdateRequest):
    return await user_crud.update_user_avatar(user_id, payload.avatar_s3_url)


@router.post("/users/{user_id}/avatar/upload", response_model=UserAvatarUploadResponse)
async def upload_user_avatar(user_id: str, file: UploadFile):
    upload = await voice_service.upload_image_file(file)
    user = await user_crud.update_user_avatar(user_id, upload.s3_url)
    return UserAvatarUploadResponse(upload=upload, user=user)


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
