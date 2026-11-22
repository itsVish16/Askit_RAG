"""S3 helpers for presigned uploads and worker downloads."""

import os
import tempfile
import uuid

import boto3
from botocore.client import Config as BotocoreConfig
from botocore.exceptions import ClientError

from app.config import settings

_client = None


def _s3():
    global _client
    if _client is None:
        kwargs = {"region_name": settings.AWS_REGION}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        if settings.S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        else:
            kwargs["config"] = BotocoreConfig(s3={"addressing_style": "virtual"})
        _client = boto3.client("s3", **kwargs)
    return _client


def is_configured() -> bool:
    return bool(settings.S3_BUCKET_NAME)


def generate_presigned_upload(
    extension: str = "pdf",
    content_type: str = "application/pdf",
    user_id: str | None = None,
) -> dict:
    clean_ext = extension.lstrip(".").lower()
    prefix = f"uploads/{user_id}" if user_id else "uploads"
    file_key = f"{prefix}/{uuid.uuid4().hex}.{clean_ext}"
    url = _s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.S3_BUCKET_NAME,
            "Key": file_key,
            "ContentType": content_type,
        },
        ExpiresIn=settings.S3_PRESIGN_EXPIRY,
    )
    return {"upload_url": url, "file_key": file_key}


def head_object(file_key: str) -> dict | None:
    try:
        return _s3().head_object(Bucket=settings.S3_BUCKET_NAME, Key=file_key)
    except ClientError:
        return None


def download_to_temp(file_key: str) -> str:
    ext = os.path.splitext(file_key)[1] or ".pdf"
    fd, path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    with open(path, "wb") as f:
        _s3().download_fileobj(settings.S3_BUCKET_NAME, file_key, f)
    return path
