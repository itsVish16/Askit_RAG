"""S3 helpers for presigned upload URLs + worker downloads.

The frontend never touches AWS creds — it gets a time-limited presigned URL
from the backend and uploads directly to S3. The worker downloads the file
from S3 to a temp path before processing.
"""

import os
import tempfile
import uuid

import boto3
from botocore.client import Config as BotocoreConfig
from botocore.exceptions import ClientError

from app.config import settings

_client = None


def _s3():
    """Lazy S3 client, same pattern as app/queue/sqs.py."""
    global _client
    if _client is None:
        kwargs = {"region_name": settings.AWS_REGION}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        if settings.S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        else:
            # Force virtual-hosted-style so presigned URLs use the correct
            # regional endpoint (e.g. bucket.s3.us-west-2.amazonaws.com)
            # instead of the global s3.amazonaws.com endpoint, which would
            # return a 307 redirect that breaks browser PUTs.
            kwargs["config"] = BotocoreConfig(s3={"addressing_style": "virtual"})
        _client = boto3.client("s3", **kwargs)
    return _client


def is_configured() -> bool:
    """True iff we have an S3 bucket configured for presigned uploads."""
    return bool(settings.S3_BUCKET_NAME)


def generate_presigned_upload(
    extension: str = "pdf", content_type: str = "application/pdf"
) -> dict:
    """Create a presigned PUT URL for a random S3 key. Returns
    {upload_url, file_key} — the frontend PUTs the file bytes to upload_url,
    then calls /ingest/pdf with file_key."""
    file_key = f"uploads/{uuid.uuid4().hex}.{extension.lstrip('.')}"
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
    """Get S3 object metadata (ContentLength, ContentType). Returns None if
    the object doesn't exist or access is denied."""
    try:
        return _s3().head_object(Bucket=settings.S3_BUCKET_NAME, Key=file_key)
    except ClientError:
        return None


def download_to_temp(file_key: str) -> str:
    """Download an S3 object to a temp file, return the local path.
    The caller / mark_done_node should clean up the temp file (os.unlink)."""
    ext = os.path.splitext(file_key)[1] or ".pdf"
    # mkstemp gives a fd + path that we own (no context-manager requirement).
    fd, path = tempfile.mkstemp(suffix=ext)
    os.close(fd)  # close the fd; we re-open via download_fileobj
    with open(path, "wb") as f:
        _s3().download_fileobj(settings.S3_BUCKET_NAME, file_key, f)
    return path
