import asyncio
import hashlib
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.config import settings
from app.core.security import UserPublic
from app.ingest_worker.flow import worker_agent
from app.queue import s3 as s3_queue
from app.queue import sqs
from app.queue import status as ingest_status

router = APIRouter()

_MAGIC_SIGS: dict[str, bytes] = {"pdf": b"%PDF-"}

_SUPPORTED_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def _supported_extensions() -> set[str]:
    return {
        e.strip().lstrip(".").lower()
        for e in settings.INGEST_SUPPORTED_EXTENSIONS.split(",")
        if e.strip()
    }


def _ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _validate_extension(filename: str) -> str:
    ext = _ext_of(filename)
    supported = _supported_extensions()
    if ext not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{filename}'. Supported: {sorted(supported)}.",
        )
    return ext


def _validate_upload(raw: bytes, declared_filename: str) -> None:
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Empty upload.")
    max_bytes = settings.MAX_PDF_SIZE_MB * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload too large: {len(raw)} bytes > {max_bytes} (MAX_PDF_SIZE_MB={settings.MAX_PDF_SIZE_MB}).",
        )
    ext = _validate_extension(declared_filename)
    magic = _MAGIC_SIGS.get(ext)
    if magic is not None and not raw.startswith(magic):
        raise HTTPException(
            status_code=400,
            detail=f"File is not a real {ext.upper()} (missing {magic!r} magic header).",
        )


class IngestResponse(BaseModel):
    job_id: str
    user_id: str
    state: str
    num_chunks: int | None
    file_path: str | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    state: str | None
    user_id: str | None
    attempts: int | None
    num_chunks: int | None
    error: str | None
    file_path: str | None
    sha256: str | None
    created_at: str | None
    updated_at: str | None


class PresignIn(BaseModel):
    filename: str = "upload.pdf"


class PresignOut(BaseModel):
    upload_url: str
    file_key: str


class S3IngestIn(BaseModel):
    file_key: str
    filename: str = "upload.pdf"


def _save_upload(raw: bytes, user_id: str, ext: str) -> tuple[str, str, str]:
    job_id = uuid.uuid4().hex
    upload_dir = settings.INGEST_UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    suffix = f".{ext}" if ext else ""
    file_path = os.path.join(upload_dir, f"{job_id}{suffix}")
    with open(file_path, "wb") as buf:
        buf.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    return job_id, file_path, sha


def _enforce_upload_quota(user_id: str) -> None:
    if ingest_status.count_user_completed_jobs(user_id) >= settings.MAX_PDFS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"Upload limit reached: {settings.MAX_PDFS_PER_USER} documents per user.",
        )


def _row_to_job_response(r: dict) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=r["job_id"],
        state=r.get("state"),
        user_id=r.get("user_id"),
        attempts=r.get("attempts"),
        num_chunks=r.get("num_chunks"),
        error=r.get("error"),
        file_path=r.get("file_path"),
        sha256=r.get("sha256"),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


@router.post("/ingest/pdf", response_model=IngestResponse)
async def ingest_pdf_endpoint(
    file: UploadFile = File(...),
    current_user: UserPublic = Depends(get_current_user),
):
    raw = await file.read()
    declared = file.filename or "upload.pdf"
    _validate_upload(raw, declared_filename=declared)

    uid = current_user.id
    _enforce_upload_quota(uid)

    ext = _ext_of(declared)
    job_id, file_path, sha = _save_upload(raw, uid, ext)
    ingest_status.create_job(job_id=job_id, user_id=uid, file_path=file_path, sha256=sha)

    if not sqs.is_configured():
        final_state = await asyncio.to_thread(
            worker_agent.invoke,
            {"job_id": job_id, "user_id": uid, "file_path": file_path, "sha256": sha, "attempts": 1},
        )
        return IngestResponse(
            job_id=job_id,
            user_id=uid,
            state="completed" if final_state.get("final_state") == "COMPLETED" else "failed",
            num_chunks=final_state.get("num_chunks", 0),
            file_path=file_path,
        )

    try:
        sqs.send_job(job_id=job_id, file_path=file_path, user_id=uid, sha256=sha, attempts=0)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to enqueue ingest job: {type(exc).__name__}: {exc}",
        )
    return IngestResponse(job_id=job_id, user_id=uid, state="queued", num_chunks=None, file_path=file_path)


@router.get("/ingest/jobs", response_model=list[JobStatusResponse])
async def list_my_jobs(current_user: UserPublic = Depends(get_current_user)):
    return [_row_to_job_response(r) for r in ingest_status.list_jobs_by_user(current_user.id)]


@router.get("/ingest/status/{job_id}", response_model=JobStatusResponse)
async def ingest_status_endpoint(job_id: str, current_user: UserPublic = Depends(get_current_user)):
    row = ingest_status.get_job(job_id)
    if row is None or row.get("user_id") != current_user.id:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    return _row_to_job_response(row)


@router.post("/ingest/presign", response_model=PresignOut)
async def presign_upload(
    body: PresignIn,
    current_user: UserPublic = Depends(get_current_user),
):
    if not s3_queue.is_configured():
        raise HTTPException(status_code=400, detail="S3 not configured (S3_BUCKET_NAME is empty).")
    ext = _validate_extension(body.filename)
    mime = _SUPPORTED_MIME.get(ext, "application/octet-stream")
    result = s3_queue.generate_presigned_upload(extension=ext, content_type=mime, user_id=current_user.id)
    return PresignOut(**result)


@router.post("/ingest/s3", response_model=IngestResponse)
async def ingest_s3(
    body: S3IngestIn,
    current_user: UserPublic = Depends(get_current_user),
):
    if not s3_queue.is_configured():
        raise HTTPException(status_code=400, detail="S3 not configured (S3_BUCKET_NAME is empty).")

    uid = current_user.id
    expected_prefix = f"uploads/{uid}/"
    if not body.file_key.startswith(expected_prefix) or ".." in body.file_key:
        raise HTTPException(status_code=403, detail="Invalid S3 object key for current user.")
    _validate_extension(body.file_key)

    obj = s3_queue.head_object(body.file_key)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"S3 object '{body.file_key}' not found.")
    max_bytes = settings.MAX_PDF_SIZE_MB * 1024 * 1024
    if obj.get("ContentLength", 0) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Upload too large: > {settings.MAX_PDF_SIZE_MB} MB.")

    _enforce_upload_quota(uid)

    s3_path = f"s3://{settings.S3_BUCKET_NAME}/{body.file_key}"
    job_id = uuid.uuid4().hex
    # SHA-256 is computed in fetch_file_node after downloading the real S3 bytes.
    sha = ""
    ingest_status.create_job(job_id=job_id, user_id=uid, file_path=s3_path, sha256=sha)

    if not sqs.is_configured():
        final_state = await asyncio.to_thread(
            worker_agent.invoke,
            {"job_id": job_id, "user_id": uid, "file_path": s3_path, "sha256": sha, "attempts": 1},
        )
        return IngestResponse(
            job_id=job_id,
            user_id=uid,
            state="completed" if final_state.get("final_state") == "COMPLETED" else "failed",
            num_chunks=final_state.get("num_chunks", 0),
            file_path=s3_path,
        )

    try:
        sqs.send_job(job_id=job_id, file_path=s3_path, user_id=uid, sha256=sha, attempts=0)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to enqueue ingest job: {type(exc).__name__}: {exc}")
    return IngestResponse(job_id=job_id, user_id=uid, state="queued", num_chunks=None, file_path=s3_path)
