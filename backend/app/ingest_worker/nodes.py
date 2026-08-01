"""Nodes for the ingest worker LangGraph.

`error_type` is the contract between nodes and conditional edges: a node sets
it to "permanent" (poison-pill, delete SQS msg) or "transient" (let SQS
visibility-timeout redeliver). No LLM calls here, so the only observability is
the Opik span the runner wraps around the graph (rule #3 still holds if a
node later adds an LLM call).
"""

import os
from typing import TypedDict

from app.config import settings
from app.db.ingestion import chunk_documents, embed_and_upsert, load_pdf_documents
from app.ingest_worker.repo import chunk_ids
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
    error_type: str | None  # None => keep flowing; "permanent"/"transient" => terminal
    last_error: str | None
    final_state: str  # COMPLETED | FAILED | RETRYING


def fetch_file_node(state: WorkerGraphState):
    """Verify the spooled file still exists. Treating 'missing' as permanent
    (not retrying) avoids an SQS poison-pill loop — the job can never succeed
    if the file is gone."""
    if not os.path.exists(state["file_path"]):
        return {"error_type": "permanent", "last_error": f"file not found: {state['file_path']}"}
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
    """Idempotent Qdrant upsert. Qdrant 5xx/network blips are transient — left
    to SQS visibility timeout, the redelivered message's deterministic point_id
    makes the second attempt overwrite the first."""
    if state.get("error_type"):
        return {}
    try:
        ids = chunk_ids(state["user_id"], state["sha256"], state["num_chunks"])
        embed_and_upsert(state["chunks"], ids=ids)
    except Exception as exc:
        return {"error_type": "transient", "last_error": f"embed/upsert failed: {exc}"}
    return {}


def mark_done_node(state: WorkerGraphState):
    """Terminal: write the sqlite row + free RAM. SQS message lifecycle is
    owned by the runner (NOT here) so the delete decision is decoupled from
    the sqlite side and we can unit-test this without a fake SQS."""
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
        if not settings.INGEST_KEEP_PDF_AFTER_SUCCESS:
            try:
                os.remove(state["file_path"])
            except OSError:
                pass
    # Drop heavy fields — the runner keeps the state object for logging only.
    return {"pages": None, "chunks": None, "final_state": final}


def route_after_node(state: WorkerGraphState) -> str:
    """'ok' for the happy path, 'error' to short-circuit to mark_done."""
    return "error" if state.get("error_type") else "ok"
