from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile, status

from app.schemas.crud import (
    UploadedFileResponse,
    UserVoiceUpdateRequest,
    VoiceCloneResponse,
    VoiceSpeakRequest,
)
from app.services import user_crud
from app.services.media_service import generate_download_url, upload_file_to_s3

load_dotenv()

_ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

_ALLOWED_VOICE_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/mp4",
    "audio/x-m4a",
    "audio/flac",
}


@dataclass(frozen=True)
class TtsAudioResult:
    audio_bytes: bytes
    content_type: str


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _infer_filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = Path(path).name
    if not name:
        return "voice_sample.wav"
    return name


def _infer_content_type_from_filename(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "audio/wav"


def _elevenlabs_headers(accept: str = "application/json") -> dict[str, str]:
    return {
        "xi-api-key": _get_env("ELEVENLABS_API_KEY"),
        "accept": accept,
    }


def _format_elevenlabs_error(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            status_code = detail.get("status")
            message = detail.get("message")
            if status_code and message:
                return f"{status_code}: {message}"
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message

    body = response.text.strip()
    if body:
        return body[:500]
    return str(exc)


async def upload_image_file(file: UploadFile) -> UploadedFileResponse:
    result = await upload_file_to_s3(
        upload=file,
        prefix="uploads/images",
        allowed_content_types=_ALLOWED_IMAGE_CONTENT_TYPES,
    )
    return UploadedFileResponse(**result.__dict__)


async def upload_voice_file(file: UploadFile) -> UploadedFileResponse:
    result = await upload_file_to_s3(
        upload=file,
        prefix="uploads/voices",
        allowed_content_types=_ALLOWED_VOICE_CONTENT_TYPES,
    )
    return UploadedFileResponse(**result.__dict__)


async def update_user_voice_sample(user_id: str, payload: UserVoiceUpdateRequest):
    return await user_crud.update_user_voice_fields(
        user_id,
        voice_sample_s3_url=payload.voice_sample_s3_url,
        voice_status="uploaded",
        clear_eleven_voice_id=True,
    )


async def clone_user_voice(user_id: str) -> VoiceCloneResponse:
    user = await user_crud.get_user(user_id)
    if not user.voice_sample_s3_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no voice_sample_s3_url.",
        )

    await user_crud.update_user_voice_fields(user_id, voice_status="training")

    sample_url = generate_download_url(user.voice_sample_s3_url, expires_in=900)
    sample_filename = _infer_filename_from_url(user.voice_sample_s3_url)

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            sample_response = await client.get(sample_url)
            sample_response.raise_for_status()
            sample_bytes = sample_response.content

            create_voice_resp = await client.post(
                "https://api.elevenlabs.io/v1/voices/add",
                headers=_elevenlabs_headers(),
                data={
                    "name": f"{(user.full_name or 'user').strip()}-{str(user.id)[:8]}",
                    "description": "Voice cloned from user sample",
                },
                files={
                    "files": (
                        sample_filename,
                        sample_bytes,
                        _infer_content_type_from_filename(sample_filename),
                    )
                },
            )
            create_voice_resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        await user_crud.update_user_voice_fields(user_id, voice_status="failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs voice clone failed: {_format_elevenlabs_error(exc)}",
        )
    except httpx.HTTPError as exc:
        await user_crud.update_user_voice_fields(user_id, voice_status="failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs voice clone failed: {exc}",
        )

    payload = create_voice_resp.json()
    eleven_voice_id = payload.get("voice_id")
    if not eleven_voice_id:
        await user_crud.update_user_voice_fields(user_id, voice_status="failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ElevenLabs did not return voice_id.",
        )

    updated = await user_crud.update_user_voice_fields(
        user_id,
        voice_status="ready",
        eleven_voice_id=eleven_voice_id,
    )
    return VoiceCloneResponse(
        user_id=updated.id,
        voice_status=updated.voice_status or "ready",
        eleven_voice_id=eleven_voice_id,
    )


async def speak_with_user_voice(user_id: str, payload: VoiceSpeakRequest) -> TtsAudioResult:
    user = await user_crud.get_user(user_id)
    if not user.eleven_voice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no eleven_voice_id. Clone voice first.",
        )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{user.eleven_voice_id}?output_format=mp3_44100_128",
                headers={
                    **_elevenlabs_headers(accept="audio/mpeg"),
                    "Content-Type": "application/json",
                },
                json={
                    "text": payload.text,          # text đã được chuẩn hóa cho tiếng Việt
                    "model_id": payload.model_id,  # hoặc model Eleven v3 nếu tài khoản/flow của bạn dùng được
                    "language_code": "vi",
                    "voice_settings": {
                        "stability": 0.65,
                        "similarity_boost": 0.7,
                        "style": 0.0,
                        "speed": 0.95,
                        "use_speaker_boost": True
                    }
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs text-to-speech failed: {_format_elevenlabs_error(exc)}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs text-to-speech failed: {exc}",
        )

    return TtsAudioResult(
        audio_bytes=response.content,
        content_type=response.headers.get("content-type", "audio/mpeg"),
    )
