import hashlib
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.config import settings
from app.core.security import UserPublic
from app.db.ingestion import ingest_pdf
from app.queue import sqs
from app.queue import status as ingest_status

router = APIRouter()

# Magic-byte signatures to reject renamed executables/scripts. Only PDF has a
# reliable magic header; text/image types are accepted by extension + size.
_MAGIC_SIGS: dict[str, bytes] = {"pdf": b"%PDF-"}


def _supported_extensions() -> set[str]:
    return {
        e.strip().lstrip(".").lower()
        for e in settings.INGEST_SUPPORTED_EXTENSIONS.split(",")
        if e.strip()
    }


def _ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _validate_upload(raw: bytes, declared_filename: str) -> None:
    """Defensive checks before handing bytes to a loader. Size cap runs before
    magic-bytes so an attacker can't push gigabytes through the magic path."""
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Empty upload.")
    max_bytes = settings.MAX_PDF_SIZE_MB * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload too large: {len(raw)} bytes > {max_bytes} (MAX_PDF_SIZE_MB={settings.MAX_PDF_SIZE_MB}).",
        )
    ext = _ext_of(declared_filename)
    supported = _supported_extensions()
    if ext not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{declared_filename}'. Supported: {sorted(supported)}.",
        )
    magic = _MAGIC_SIGS.get(ext)
    if magic is not None and not raw.startswith(magic):
        raise HTTPException(
            status_code=400,
            detail=f"File is not a real {ext.upper()} (missing {magic!r} magic header).",
        )


class IngestResponse(BaseModel):
    job_id: str
    user_id: str
    state: str  # 'queued' (async) | 'completed'|'empty' (inline fallback)
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


def _save_upload(raw: bytes, user_id: str, ext: str) -> tuple[str, str, str]:
    """Persist bytes to INGEST_UPLOAD_DIR/{job_id}.{ext}, return (job_id, file_path, sha256).
    The extension is preserved so the loader registry can dispatch by type."""
    job_id = uuid.uuid4().hex
    upload_dir = settings.INGEST_UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    suffix = f".{ext}" if ext else ""
    file_path = os.path.join(upload_dir, f"{job_id}{suffix}")
    with open(file_path, "wb") as buf:
        buf.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    return job_id, file_path, sha


@router.post("/ingest/pdf", response_model=IngestResponse)
async def ingest_pdf_endpoint(
    file: UploadFile = File(...),
    current_user: UserPublic = Depends(get_current_user),
):
    """Queue an uploaded file for async embedding by the in-process worker.

    Auth-required; the file is owned by the logged-in user (retrieval will be
    scoped to their chunks). Enforces the per-user PDF cap (MAX_PDFS_PER_USER)
    and the upload validation (size/magic/extension). validate -> spool to
    data/uploads/{job_id}.<ext> -> if SQS configured: write PENDING sqlite row
    + publish pointer msg -> return 'queued' now. Else inline ingest_pdf()
    fallback (dev without a queue).
    """
    raw = await file.read()
    declared = file.filename or "upload.pdf"
    _validate_upload(raw, declared_filename=declared)

    uid = current_user.id
    if ingest_status.count_user_completed_jobs(uid) >= settings.MAX_PDFS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"Upload limit reached: {settings.MAX_PDFS_PER_USER} PDFs per user. "
            "Remove one before uploading another.",
        )

    ext = _ext_of(declared)
    job_id, file_path, sha = _save_upload(raw, uid, ext)

    if not sqs.is_configured():
        result = ingest_pdf(file_path, user_id=uid)
        # Inline path: still count toward the cap by recording the job.
        ingest_status.create_job(job_id=job_id, user_id=uid, file_path=file_path, sha256=sha)
        ingest_status.set_state(job_id, "COMPLETED" if result["status"] == "ok" else "FAILED", num_chunks=result["num_chunks"])
        return IngestResponse(
            job_id=job_id,
            user_id=uid,
            state=result["status"],
            num_chunks=result["num_chunks"],
            file_path=file_path,
        )

    ingest_status.create_job(job_id=job_id, user_id=uid, file_path=file_path, sha256=sha)
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
    """List the logged-in user's ingest jobs (newest first) — drives the
    'My Documents' UI."""
    rows = ingest_status.list_jobs_by_user(current_user.id)
    return [
        JobStatusResponse(
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
        for r in rows
    ]


@router.get("/ingest/status/{job_id}", response_model=JobStatusResponse)
async def ingest_status_endpoint(job_id: str, current_user: UserPublic = Depends(get_current_user)):
    """Poll a job_id for its async-ingest state (reads sqlite, survives restarts).
    Only the job's owner may read it."""
    row = ingest_status.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    if row.get("user_id") != current_user.id:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")  # hide existence
    return JobStatusResponse(
        job_id=row["job_id"],
        state=row.get("state"),
        user_id=row.get("user_id"),
        attempts=row.get("attempts"),
        num_chunks=row.get("num_chunks"),
        error=row.get("error"),
        file_path=row.get("file_path"),
        sha256=row.get("sha256"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )
