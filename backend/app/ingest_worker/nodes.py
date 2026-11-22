"""LangGraph nodes for the async document ingestion worker."""

import hashlib
import os
from typing import TypedDict

from app.config import settings
from app.db.ingestion import chunk_documents, embed_and_upsert, load_pdf_documents
from app.ingest_worker.repo import chunk_ids
from app.queue import s3 as s3_queue
from app.queue import status


class WorkerGraphState(TypedDict, total=False):
    job_id: str
    file_path: str
    user_id: str
    sha256: str
    attempts: int
    pages: list
    num_pages: int
    chunks: list
    num_chunks: int
    error_type: str | None
    last_error: str | None
    final_state: str
    _s3_temp: str | None


def _is_s3_path(path: str) -> bool:
    return path.startswith("s3://")


def _parse_s3_path(path: str) -> str | None:
    if not path.startswith("s3://"):
        return None
    parts = path.split("/", 3)
    return parts[3] if len(parts) >= 4 else None


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def fetch_file_node(state: WorkerGraphState):
    """Verify local file or download S3 object to a temp file and ensure SHA-256."""
    fp = state["file_path"]

    if _is_s3_path(fp):
        s3_key = _parse_s3_path(fp)
        if s3_key is None:
            return {"error_type": "permanent", "last_error": f"malformed S3 path: {fp}"}
        try:
            temp = s3_queue.download_to_temp(s3_key)
        except Exception as exc:
            return {"error_type": "permanent", "last_error": f"S3 download failed: {exc}"}
        sha = state.get("sha256") or _sha256_file(temp)
        return {"file_path": temp, "_s3_temp": temp, "sha256": sha}

    if not os.path.exists(fp):
        return {"error_type": "permanent", "last_error": f"file not found: {fp}"}
    if not state.get("sha256"):
        return {"sha256": _sha256_file(fp)}
    return {}


def extract_pdf_node(state: WorkerGraphState):
    if state.get("error_type"):
        return {}
    try:
        pages = load_pdf_documents(state["file_path"], state["user_id"])
    except Exception as exc:
        return {"error_type": "permanent", "last_error": f"parse failed: {exc}"}
    if not pages:
        return {"error_type": "permanent", "last_error": "no extractable pages"}
    if len(pages) > settings.MAX_PDF_PAGES:
        return {
            "error_type": "permanent",
            "last_error": f"too many pages ({len(pages)} > {settings.MAX_PDF_PAGES})",
        }
    return {"pages": pages, "num_pages": len(pages)}


def chunk_node(state: WorkerGraphState):
    if state.get("error_type"):
        return {}
    try:
        chunks = chunk_documents(state["pages"])
    except Exception as exc:
        return {"error_type": "permanent", "last_error": f"chunking failed: {exc}"}
    if not chunks:
        return {"error_type": "permanent", "last_error": "no chunks after split"}
    return {"chunks": chunks, "num_chunks": len(chunks)}


def embed_upsert_node(state: WorkerGraphState):
    if state.get("error_type"):
        return {}
    try:
        ids = chunk_ids(state["user_id"], state["sha256"], state["num_chunks"])
        embed_and_upsert(state["chunks"], ids=ids)
    except Exception as exc:
        return {"error_type": "transient", "last_error": f"embed/upsert failed: {exc}"}
    return {}


def mark_done_node(state: WorkerGraphState):
    """Persist terminal status, release memory, and remove any S3 temp file."""
    et = state.get("error_type")
    job_id = state["job_id"]
    attempts = state.get("attempts", 0)

    if et == "permanent":
        status.set_state(job_id, "FAILED", attempts=attempts, error=state.get("last_error"))
        final = "FAILED"
    elif et == "transient":
        status.set_state(job_id, "RETRYING", attempts=attempts + 1, error=state.get("last_error"))
        final = "RETRYING"
    else:
        status.set_state(job_id, "COMPLETED", attempts=attempts, num_chunks=state["num_chunks"])
        final = "COMPLETED"
        if not settings.INGEST_KEEP_PDF_AFTER_SUCCESS and not state.get("_s3_temp"):
            try:
                os.remove(state["file_path"])
            except OSError:
                pass

    s3_temp = state.get("_s3_temp")
    if s3_temp:
        try:
            os.unlink(s3_temp)
        except OSError:
            pass

    return {"pages": None, "chunks": None, "final_state": final}


def route_after_node(state: WorkerGraphState) -> str:
    return "error" if state.get("error_type") else "ok"
