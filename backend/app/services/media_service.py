"""
Media Service – S3 upload & fetch helpers.

Required environment variables:
	AWS_REGION=<aws-region>
	AWS_S3_BUCKET_NAME=<bucket-name>

Optional environment variables:
	AWS_ACCESS_KEY_ID=<access-key>
	AWS_SECRET_ACCESS_KEY=<secret-key>
	AWS_SESSION_TOKEN=<session-token>
	AWS_S3_ENDPOINT_URL=<custom-s3-endpoint>
	AWS_S3_PRESIGN_EXPIRE_SECONDS=900
	MEDIA_MAX_FILE_SIZE_MB=100
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import find_dotenv, load_dotenv
from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

load_dotenv(find_dotenv(usecwd=True))
load_dotenv()

_ALLOWED_MIME_TYPES = {
	"image/jpeg",
	"image/png",
	"image/webp",
	"image/heic",
	"image/heif",
	"video/mp4",
	"video/quicktime",
	"video/webm",
	"video/x-msvideo",
	"video/x-matroska",
}

_MIME_TO_EXT = {
	"image/jpeg": ".jpg",
	"image/png": ".png",
	"image/webp": ".webp",
	"image/heic": ".heic",
	"image/heif": ".heif",
	"video/mp4": ".mp4",
	"video/quicktime": ".mov",
	"video/webm": ".webm",
	"video/x-msvideo": ".avi",
	"video/x-matroska": ".mkv",
}


@dataclass(frozen=True)
class UploadMediaResult:
	s3_key: str
	s3_url: str
	media_type: str
	content_type: str
	size_bytes: int


@dataclass(frozen=True)
class PresignedUploadResult:
	upload_url: str
	s3_key: str
	s3_url: str
	method: str
	expires_in: int


def _get_env(name: str) -> str:
	value = os.getenv(name)
	if not value:
		raise RuntimeError(f"Missing required environment variable: {name}")
	return value


def _get_bucket_name() -> str:
	return _get_env("AWS_S3_BUCKET_NAME")


def _get_region() -> str:
	return _get_env("AWS_REGION")


def _get_max_file_size_bytes() -> int:
	size_mb = int(os.getenv("MEDIA_MAX_FILE_SIZE_MB", "100"))
	if size_mb <= 0:
		raise RuntimeError("MEDIA_MAX_FILE_SIZE_MB must be greater than 0")
	return size_mb * 1024 * 1024


def _get_presign_expire_seconds() -> int:
	expire = int(os.getenv("AWS_S3_PRESIGN_EXPIRE_SECONDS", "900"))
	if expire <= 0:
		raise RuntimeError("AWS_S3_PRESIGN_EXPIRE_SECONDS must be greater than 0")
	return min(expire, 7 * 24 * 60 * 60)


def _normalized_endpoint_base() -> str | None:
	endpoint = os.getenv("AWS_S3_ENDPOINT_URL")
	if not endpoint:
		return None

	parsed = urlparse(endpoint)
	if not parsed.scheme or not parsed.netloc:
		raise RuntimeError("AWS_S3_ENDPOINT_URL must be a valid URL")

	netloc = parsed.netloc.lower()
	if ".s3." in netloc and netloc.endswith("amazonaws.com"):
		return None

	base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
	return base


@lru_cache(maxsize=1)
def _get_s3_client() -> BaseClient:
	session = boto3.session.Session(
		aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
		aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
		aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
		region_name=_get_region(),
	)
	return session.client(
		"s3",
		endpoint_url=_normalized_endpoint_base(),
		config=Config(
			retries={"max_attempts": 10, "mode": "adaptive"},
			connect_timeout=5,
			read_timeout=60,
			tcp_keepalive=True,
		),
	)


def _public_s3_url(bucket: str, key: str) -> str:
	endpoint = _normalized_endpoint_base()
	if endpoint:
		if urlparse(endpoint).netloc.startswith(f"{bucket}."):
			return f"{endpoint}/{key}"
		return f"{endpoint}/{bucket}/{key}"
	region = _get_region()
	if region == "us-east-1":
		return f"https://{bucket}.s3.amazonaws.com/{key}"
	return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def _extract_s3_key(s3_key_or_url: str) -> str:
	if s3_key_or_url.startswith("s3://"):
		parsed = urlparse(s3_key_or_url)
		key = parsed.path.lstrip("/")
		if not key:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail="Invalid S3 URL: missing object key.",
			)
		return key

	if s3_key_or_url.startswith("http://") or s3_key_or_url.startswith("https://"):
		parsed = urlparse(s3_key_or_url)
		key = parsed.path.lstrip("/")
		if not key:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail="Invalid S3 URL: missing object key.",
			)

		bucket = _get_bucket_name()
		path_parts = key.split("/", 1)
		if len(path_parts) == 2 and path_parts[0] == bucket:
			return path_parts[1]
		return key

	return s3_key_or_url.lstrip("/")


def _file_size_bytes(file_obj: BinaryIO) -> int:
	current_pos = file_obj.tell()
	file_obj.seek(0, os.SEEK_END)
	size = file_obj.tell()
	file_obj.seek(current_pos)
	return size


def _determine_media_type(content_type: str) -> str:
	if content_type.startswith("image/"):
		return "image"
	if content_type.startswith("video/"):
		return "video"
	raise HTTPException(
		status_code=status.HTTP_400_BAD_REQUEST,
		detail="Only image and video files are supported.",
	)


def _safe_extension(upload: UploadFile) -> str:
	content_type = (upload.content_type or "").lower().strip()
	if content_type in _MIME_TO_EXT:
		return _MIME_TO_EXT[content_type]

	suffix = Path(upload.filename or "").suffix.lower()
	if suffix and len(suffix) <= 10:
		return suffix
	return ".bin"


def _safe_suffix_from_filename(filename: str) -> str:
	suffix = Path(filename).suffix.lower().strip()
	if suffix and len(suffix) <= 10:
		return suffix
	return ""


def _validate_upload(upload: UploadFile) -> tuple[str, int]:
	content_type = (upload.content_type or "").lower().strip()
	if content_type not in _ALLOWED_MIME_TYPES:
		raise HTTPException(
			status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
			detail="Unsupported media type.",
		)

	file_obj = upload.file
	file_obj.seek(0)
	size_bytes = _file_size_bytes(file_obj)
	if size_bytes <= 0:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="Uploaded file is empty.",
		)

	max_size_bytes = _get_max_file_size_bytes()
	if size_bytes > max_size_bytes:
		raise HTTPException(
			status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
			detail=f"File exceeds maximum allowed size of {max_size_bytes} bytes.",
		)

	return content_type, size_bytes


def _build_object_key(family_id: str, media_type: str, extension: str) -> str:
	now = datetime.now(timezone.utc)
	year = now.strftime("%Y")
	month = now.strftime("%m")
	day = now.strftime("%d")
	unique_id = uuid.uuid4().hex
	return f"media/{family_id}/{media_type}/{year}/{month}/{day}/{unique_id}{extension}"


def generate_upload_url(
	*,
	prefix: str,
	file_name: str,
	content_type: str,
	expires_in: int | None = None,
) -> PresignedUploadResult:
	"""Generate a presigned PUT URL and final object URL for direct client upload."""
	clean_prefix = "/".join(part for part in prefix.split("/") if part).strip()
	if not clean_prefix:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="Invalid upload prefix.",
		)

	if not file_name.strip():
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="file_name is required.",
		)

	if not content_type.strip():
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="content_type is required.",
		)

	suffix = _safe_suffix_from_filename(file_name)
	now = datetime.now(timezone.utc)
	s3_key = (
		f"{clean_prefix}/{now.strftime('%Y')}/{now.strftime('%m')}/{now.strftime('%d')}/"
		f"{uuid.uuid4().hex}{suffix}"
	)
	bucket = _get_bucket_name()

	expiration = expires_in if expires_in is not None else _get_presign_expire_seconds()
	if expiration <= 0:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="Presigned URL expiration must be greater than 0.",
		)

	try:
		client = _get_s3_client()
		upload_url = client.generate_presigned_url(
			"put_object",
			Params={
				"Bucket": bucket,
				"Key": s3_key,
				"ContentType": content_type,
			},
			ExpiresIn=min(expiration, 7 * 24 * 60 * 60),
		)
	except (ClientError, BotoCoreError) as exc:
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail=f"Failed to generate upload URL: {exc}",
		)

	return PresignedUploadResult(
		upload_url=upload_url,
		s3_key=s3_key,
		s3_url=_public_s3_url(bucket=bucket, key=s3_key),
		method="PUT",
		expires_in=min(expiration, 7 * 24 * 60 * 60),
	)


def _upload_to_s3_sync(upload: UploadFile, key: str, content_type: str) -> None:
	client = _get_s3_client()
	bucket = _get_bucket_name()
	upload.file.seek(0)
	try:
		client.upload_fileobj(
			Fileobj=upload.file,
			Bucket=bucket,
			Key=key,
			ExtraArgs={
				"ContentType": content_type,
				"ServerSideEncryption": "AES256",
			},
		)
	except ClientError as exc:
		error_code = (exc.response.get("Error") or {}).get("Code", "")
		error_msg = (exc.response.get("Error") or {}).get("Message", str(exc))
		if error_code in {"AccessDenied", "UnauthorizedOperation"}:
			raise HTTPException(
				status_code=status.HTTP_403_FORBIDDEN,
				detail=(
					"S3 upload denied by AWS IAM/Bucket policy. "
					f"Code={error_code}, message={error_msg}"
				),
			)
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail=f"S3 upload failed: {error_code or 'Unknown'} - {error_msg}",
		)
	except BotoCoreError as exc:
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail=f"S3 upload failed: {exc}",
		)


async def upload_media(upload: UploadFile, family_id: str) -> UploadMediaResult:
	"""Upload image/video to S3 and return storage metadata."""
	content_type, size_bytes = _validate_upload(upload)
	media_type = _determine_media_type(content_type)
	extension = _safe_extension(upload)
	key = _build_object_key(family_id=family_id, media_type=media_type, extension=extension)

	await run_in_threadpool(_upload_to_s3_sync, upload, key, content_type)

	bucket = _get_bucket_name()
	return UploadMediaResult(
		s3_key=key,
		s3_url=_public_s3_url(bucket=bucket, key=key),
		media_type=media_type,
		content_type=content_type,
		size_bytes=size_bytes,
	)


def generate_download_url(s3_key_or_url: str, expires_in: int | None = None) -> str:
	"""Generate a time-limited presigned GET URL for an S3 object."""
	key = _extract_s3_key(s3_key_or_url)
	if not key:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="Missing S3 object key.",
		)

	expiration = expires_in if expires_in is not None else _get_presign_expire_seconds()
	if expiration <= 0:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="Presigned URL expiration must be greater than 0.",
		)

	try:
		client = _get_s3_client()
		return client.generate_presigned_url(
			"get_object",
			Params={"Bucket": _get_bucket_name(), "Key": key},
			ExpiresIn=min(expiration, 7 * 24 * 60 * 60),
		)
	except (ClientError, BotoCoreError) as exc:
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail=f"Failed to generate presigned URL: {exc}",
		)
