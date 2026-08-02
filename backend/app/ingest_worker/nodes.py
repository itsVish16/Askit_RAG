"""Nodes for the ingest worker LangGraph.

`error_type` is the contract between nodes and conditional edges: a node sets
it to "permanent" (poison-pill, delete SQS msg) or "transient" (let SQS
visibility-timeout redeliver). No LLM calls here, so the only observability is
the Opik span the runner wraps around the graph.
"""

import os
from typing import TypedDict

from app.config import settings
from app.db.ingestion import chunk_documents, embed_and_upsert, load_pdf_documents
from app.ingest_worker.repo import chunk_ids
from app.queue import s3 as s3_queue
from app.queue import status


class WorkerGraphState(TypedDict, total=False):
    job_id: str
    file_path: str  # local path, or s3://bucket/key for S3-backed jobs
    user_id: str
    sha256: str
    attempts: int
    pages: list
    num_pages: int
    chunks: list
    num_chunks: int
    error_type: str | None
    last_error: str | None
    final_state: str  # COMPLETED | FAILED | RETRYING
    _s3_temp: str | None  # temp file path for S3-downloaded content; cleaned up in mark_done


def _is_s3_path(path: str) -> bool:
    return path.startswith("s3://")


def _parse_s3_path(path: str) -> str | None:
    """Extract the S3 key from s3://bucket/key. Returns None on malformed path."""
    if not path.startswith("s3://"):
        return None
    # s3://bucket/key -> key
    parts = path.split("/", 3)
    return parts[3] if len(parts) >= 4 else None


def fetch_file_node(state: WorkerGraphState):
    """Verify the file exists. When file_path is an s3:// URL, download from
    S3 to a temp file and override file_path. Treats missing S3 object as
    permanent (won't resolve by retrying)."""
    fp = state["file_path"]

    if _is_s3_path(fp):
        s3_key = _parse_s3_path(fp)
        if s3_key is None:
            return {"error_type": "permanent", "last_error": f"malformed S3 path: {fp}"}
        try:
            temp = s3_queue.download_to_temp(s3_key)
        except Exception as exc:
            return {"error_type": "permanent", "last_error": f"S3 download failed: {exc}"}
        return {"file_path": temp, "_s3_temp": temp}

    if not os.path.exists(fp):
        return {"error_type": "permanent", "last_error": f"file not found: {fp}"}
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
        return {"error_type": "permanent", "last_error": f"too many pages ({len(pages)} > {settings.MAX_PDF_PAGES})"}
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
    """Terminal: write the sqlite row + free RAM + clean up S3 temp file."""
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

    # Clean up S3 temp file if one was downloaded.
    s3_temp = state.get("_s3_temp")
    if s3_temp:
        try:
            os.unlink(s3_temp)
        except OSError:
            pass

    return {"pages": None, "chunks": None, "final_state": final}


def route_after_node(state: WorkerGraphState) -> str:
    return "error" if state.get("error_type") else "ok"
