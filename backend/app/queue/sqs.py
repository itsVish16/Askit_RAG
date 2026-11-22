"""SQS-backed ingestion queue client."""

import json
import threading

import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_client = None
_client_lock = threading.Lock()
_client_initialized = False


def _get_sqs_region() -> str:
    """Infer AWS region from SQS_QUEUE_URL or fall back to AWS_REGION."""
    url = settings.SQS_QUEUE_URL
    if url and "sqs." in url and ".amazonaws.com" in url:
        try:
            domain = url.split("sqs.", 1)[1].split(".amazonaws.com", 1)[0]
            if domain:
                return domain
        except Exception as exc:
            logger.warning(f"[sqs] failed to parse region from SQS_QUEUE_URL: {exc}")
    return settings.AWS_REGION


def _sqs():
    global _client, _client_initialized
    if _client_initialized:
        return _client
    with _client_lock:
        if _client_initialized:
            return _client
        kwargs = {"region_name": _get_sqs_region()}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        if settings.SQS_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.SQS_ENDPOINT_URL
        _client = boto3.client("sqs", **kwargs)
        _client_initialized = True
        return _client


def is_configured() -> bool:
    return bool(settings.SQS_QUEUE_URL)


def send_job(job_id: str, file_path: str, user_id: str, sha256: str, attempts: int = 0) -> str:
    body = json.dumps(
        {
            "job_id": job_id,
            "file_path": file_path,
            "user_id": user_id,
            "sha256": sha256,
            "attempts": attempts,
        }
    )
    try:
        resp = _sqs().send_message(QueueUrl=settings.SQS_QUEUE_URL, MessageBody=body)
        return resp.get("MessageId", "")
    except ClientError as exc:
        logger.error(f"[sqs] send_job failed: {exc}")
        raise


def receive_one():
    try:
        resp = _sqs().receive_message(
            QueueUrl=settings.SQS_QUEUE_URL,
            MaxNumberOfMessages=settings.SQS_MAX_MESSAGES,
            WaitTimeSeconds=settings.SQS_WAIT_SECONDS,
            VisibilityTimeout=settings.SQS_VISIBILITY_TIMEOUT_SEC,
            AttributeNames=["ApproximateReceiveCount"],
        )
    except ClientError as exc:
        logger.error(f"[sqs] receive_one failed: {exc}")
        return None

    msgs = resp.get("Messages") or []
    if not msgs:
        return None
    m = msgs[0]
    try:
        decoded = json.loads(m.get("Body", "{}"))
    except json.JSONDecodeError:
        delete_message(m["ReceiptHandle"])
        return None
    decoded["receipt_handle"] = m["ReceiptHandle"]
    decoded["receive_count"] = int(m.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    return decoded


def delete_message(receipt_handle: str) -> None:
    try:
        _sqs().delete_message(QueueUrl=settings.SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
    except ClientError as exc:
        logger.error(f"[sqs] delete_message failed: {exc}")
