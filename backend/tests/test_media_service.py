import os

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.services import media_service


def test_normalized_endpoint_base_ignores_aws_s3_bucket_endpoint(monkeypatch):
    monkeypatch.setenv("AWS_S3_ENDPOINT_URL", "https://mem-s3-heheboy.s3.us-east-1.amazonaws.com/media/")
    assert media_service._normalized_endpoint_base() is None


def test_normalized_endpoint_base_keeps_custom_s3_endpoint(monkeypatch):
    monkeypatch.setenv("AWS_S3_ENDPOINT_URL", "https://minio.example.internal:9000/custom/path")
    assert media_service._normalized_endpoint_base() == "https://minio.example.internal:9000"


def test_upload_to_s3_sync_access_denied_maps_to_403(monkeypatch):
    class FakeUpload:
        content_type = "image/jpeg"

        class _File:
            def seek(self, *_args, **_kwargs):
                return None

        file = _File()

    class FakeClient:
        def upload_fileobj(self, **_kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "AccessDenied",
                        "Message": "not authorized",
                    }
                },
                "PutObject",
            )

    monkeypatch.setattr(media_service, "_get_s3_client", lambda: FakeClient())
    monkeypatch.setattr(media_service, "_get_bucket_name", lambda: "demo-bucket")

    with pytest.raises(HTTPException) as exc:
        media_service._upload_to_s3_sync(FakeUpload(), "media/test.jpg", "image/jpeg")

    assert exc.value.status_code == 403
    assert "S3 upload denied" in exc.value.detail
