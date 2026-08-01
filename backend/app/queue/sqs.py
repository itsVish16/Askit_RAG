"""SQS-backed ingestion queue (the only AWS service this design touches).

PDF bytes stay on local disk (see /ingest/pdf — it writes data/uploads/{job_id}.pdf);
the SQS message is just a tiny JSON pointer:

    {"job_id": "...", "file_path": "/abs/path/to/job.pdf",
     "user_id": "...", "sha256": "...", "attempts": 0}

Well under SQS's 256 KB limit, so no S3 transit. The ingest worker
(app/ingest_worker/runner.py) runs as a daemon thread inside the FastAPI
process and calls receive_one()/delete_message() in a loop.
"""

import json
import threading

import boto3
from botocore.exceptions import ClientError

from app.config import settings

# Boto3 clients aren't strictly thread-safe by construction but reuse fine
# across threads in practice. One client, lazily built under a lock.
_client = None
_client_lock = threading.Lock()
_client_initialized = False


def _sqs():
    """Lazily build the SQS client. Reads creds from settings if present, else
    falls back to boto3's default chain (~/.aws/credentials, env, IAM)."""
    global _client, _client_initialized
    if _client_initialized:
        return _client
    with _client_lock:
        if _client_initialized:
            return _client
        kwargs = {"region_name": settings.AWS_REGION}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        if settings.SQS_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.SQS_ENDPOINT_URL
        _client = boto3.client("sqs", **kwargs)
        _client_initialized = True
        return _client


def is_configured() -> bool:
    """True iff we have a queue URL we can publish to."""
    return bool(settings.SQS_QUEUE_URL)


def send_job(job_id: str, file_path: str, user_id: str, sha256: str, attempts: int = 0) -> str:
    """Publish one ingest job. Returns SQS MessageId. No MessageDeduplicationId
    — we rely on idempotent upserts at the worker (deterministic point_id)
    instead, so an at-least-once redelivery overwrites rather than duplicates."""
    body = json.dumps(
        {"job_id": job_id, "file_path": file_path, "user_id": user_id, "sha256": sha256, "attempts": attempts}
    )
    try:
        resp = _sqs().send_message(
            QueueUrl=settings.SQS_QUEUE_URL,
            MessageBody=body,
            VisibilityTimeout=settings.SQS_VISIBILITY_TIMEOUT_SEC,
        )
        return resp.get("MessageId", "")
    except ClientError as exc:
        print(f"  [sqs] send_job failed: {exc}")
        raise


def receive_one():
    """Long-poll for a single ingest message. Returns None on empty poll.
    Otherwise {receipt_handle, body...} with receive_count from
    ApproximateReceiveCount so we can FAIL a job before SQS's DLQ policy kicks in."""
    try:
        resp = _sqs().receive_message(
            QueueUrl=settings.SQS_QUEUE_URL,
            MaxNumberOfMessages=settings.SQS_MAX_MESSAGES,
            WaitTimeSeconds=settings.SQS_WAIT_SECONDS,
            VisibilityTimeout=settings.SQS_VISIBILITY_TIMEOUT_SEC,
            AttributeNames=["ApproximateReceiveCount"],
        )
    except ClientError as exc:
        print(f"  [sqs] receive_one failed: {exc}")
        return None

    msgs = resp.get("Messages") or []
    if not msgs:
        return None
    m = msgs[0]
    try:
        decoded = json.loads(m.get("Body", "{}"))
    except json.JSONDecodeError:
        # Garbage a client published — delete so we don't burn visibility cycles.
        delete_message(m["ReceiptHandle"])
        return None
    decoded["receipt_handle"] = m["ReceiptHandle"]
    decoded["receive_count"] = int(m.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    return decoded


def delete_message(receipt_handle: str) -> None:
    """ACK — the worker deletes a message when done with the job. NOT deleting
    on transient failure is what gives us visibility-timeout redelivery free."""
    try:
        _sqs().delete_message(QueueUrl=settings.SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
    except ClientError as exc:
        print(f"  [sqs] delete_message failed: {exc}")
