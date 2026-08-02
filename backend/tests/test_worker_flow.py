"""Tests for the ingest-worker LangGraph pipeline — `app/ingest_worker/`.

These exercise the per-job state machine without touching SQS, Qdrant, or
Fireworks. The graph is pure Python besides the LangChain ingestion helpers
which we monkeypatch.

Verifies the conditional-edge contract:
  - On a permanent failure (missing file), `error_type="permanent"` and
    the terminal node writes sqlite `state=FAILED` with `last_error`.
  - On a transient failure inside embed_upsert, `error_type="transient"`
    routes to `mark_done` which writes sqlite `state=RETRYING`.
  - On success, sqlite `state=COMPLETED, num_chunks=N`.
"""
import importlib

import pytest


@pytest.fixture
def worker_state_module(tmp_path, monkeypatch):
    """Per-test sqlite path so we don't share jobs across tests."""
    db = tmp_path / "ingest_jobs.sqlite"
    monkeypatch.setattr("app.config.settings.INGEST_STATUS_DB_PATH", str(db))
    import app.queue.status as status
    status._conn = None
    status._initialized = False
    importlib.reload(status)
    # Reimport the runner-side modules so they pick up the fresh status
    import app.ingest_worker.flow as flow
    importlib.reload(flow)
    return flow, status


def _new_job_id():
    import uuid
    return "job_" + uuid.uuid4().hex[:8]


def test_missing_file_routes_to_failed(worker_state_module):
    flow, status = worker_state_module
    job_id = _new_job_id()
    status.create_job(job_id, "u1", "/tmp/__definitely_not_here__.pdf", "sha")

    result = flow.worker_agent.invoke(
        {
            "job_id": job_id,
            "file_path": "/tmp/__definitely_not_here__.pdf",
            "user_id": "u1",
            "sha256": "sha",
            "attempts": 0,
            "error_type": None,
            "last_error": None,
        }
    )

    assert result["final_state"] == "FAILED"
    assert result["error_type"] == "permanent"
    assert "not found" in result["last_error"]
    row = status.get_job(job_id)
    assert row["state"] == "FAILED"
    assert row["error"] is not None
    assert row["num_chunks"] is None


def test_transient_qdrant_failure_routes_to_retrying(worker_state_module, monkeypatch, tmp_path):
    flow, status = worker_state_module

    # Stub nodes' ingestion helpers to simulate a Qdrant outage mid-upsert.
    from langchain_core.documents import Document

    from app.ingest_worker import nodes
    monkeypatch.setattr(nodes, "load_pdf_documents", lambda path, user_id: [
        Document(page_content="page 1 about covid")
    ])
    monkeypatch.setattr(nodes, "chunk_documents", lambda docs: [
        Document(page_content="chunk A")
    ])

    class QdrantBoom(Exception):
        pass

    def boom(*args, **kwargs):
        raise QdrantBoom("Qdrant 503")
    monkeypatch.setattr(nodes, "embed_and_upsert", boom)

    # fetch_file_node does os.path.exists(...), so create a real (empty) file
    # so the graph proceeds past fetch_file.
    fake_pdf = tmp_path / "will_extract.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 stub")

    job_id = _new_job_id()
    status.create_job(job_id, "u1", str(fake_pdf), "sha")

    result = flow.worker_agent.invoke(
        {
            "job_id": job_id,
            "file_path": str(fake_pdf),
            "user_id": "u1",
            "sha256": "sha",
            "attempts": 2,
            "error_type": None,
            "last_error": None,
        }
    )

    assert result["final_state"] == "RETRYING"
    assert result["error_type"] == "transient"
    assert "Qdrant 503" in result["last_error"]
    row = status.get_job(job_id)
    assert row["state"] == "RETRYING"
    # Per the contract: attempts is bumped by 1 on RETRYING
    assert row["attempts"] == 3


def test_permanent_failure_on_empty_pdf(worker_state_module, monkeypatch, tmp_path):
    """PyPDFLoader happily returns 0 pages for some bad PDFs. The node
    treats this as permanent so we don't burn SQS retries."""
    flow, status = worker_state_module
    from app.ingest_worker import nodes
    monkeypatch.setattr(nodes, "load_pdf_documents", lambda path, user_id: [])
    monkeypatch.setattr(nodes, "chunk_documents", lambda docs: [])

    # Real file so fetch_file_node passes; extract_pdf_node stubbed to
    # return [] which forces the "no pages" permanent branch.
    fake_pdf = tmp_path / "empty.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 stub")

    job_id = _new_job_id()
    status.create_job(job_id, "u1", str(fake_pdf), "sha")

    result = flow.worker_agent.invoke({
        "job_id": job_id, "file_path": str(fake_pdf),
        "user_id": "u1", "sha256": "sha", "attempts": 0,
        "error_type": None, "last_error": None,
    })

    assert result["final_state"] == "FAILED"
    assert result["error_type"] == "permanent"
    row = status.get_job(job_id)
    assert row["state"] == "FAILED"


def test_too_many_pages_routes_to_failed(worker_state_module, monkeypatch, tmp_path):
    """Hard cap protects the worker from OOM on a 10k-page PDF."""
    flow, status = worker_state_module
    from langchain_core.documents import Document

    from app.config import settings as cfg
    from app.ingest_worker import nodes

    monkeypatch.setattr(
        nodes,
        "load_pdf_documents",
        lambda path, user_id: [Document(page_content=f"p{i}") for i in range(cfg.MAX_PDF_PAGES + 10)],
    )

    fake_pdf = tmp_path / "huge.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 stub")

    job_id = _new_job_id()
    status.create_job(job_id, "u1", str(fake_pdf), "sha")
    result = flow.worker_agent.invoke({
        "job_id": job_id, "file_path": str(fake_pdf),
        "user_id": "u1", "sha256": "sha", "attempts": 0,
        "error_type": None, "last_error": None,
    })
    assert result["final_state"] == "FAILED"
    assert "too many" in result["last_error"]


def test_happy_path_records_completed(worker_state_module, monkeypatch, tmp_path):
    flow, status = worker_state_module
    from langchain_core.documents import Document

    from app.ingest_worker import nodes

    monkeypatch.setattr(nodes, "load_pdf_documents", lambda path, user_id: [
        Document(page_content="page 1"), Document(page_content="page 2")
    ])
    monkeypatch.setattr(nodes, "chunk_documents", lambda docs: [
        Document(page_content="chunk A"), Document(page_content="chunk B"),
        Document(page_content="chunk C"),
    ])
    received = {}
    def fake_upsert(chunks, ids=None, **kwargs):
        received["n"] = len(chunks)
        received["ids"] = ids
    monkeypatch.setattr(nodes, "embed_and_upsert", fake_upsert)

    fake_pdf = tmp_path / "happy.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 stub")

    job_id = _new_job_id()
    status.create_job(job_id, "u1", str(fake_pdf), "sha")
    result = flow.worker_agent.invoke({
        "job_id": job_id, "file_path": str(fake_pdf),
        "user_id": "u1", "sha256": "sha", "attempts": 0,
        "error_type": None, "last_error": None,
    })

    assert result["final_state"] == "COMPLETED"
    assert received["n"] == 3
    # Idempotent ids were computed by repo.chunk_ids
    assert received["ids"] is not None and len(received["ids"]) == 3
    # All ids are unique
    assert len(set(received["ids"])) == 3
    row = status.get_job(job_id)
    assert row["state"] == "COMPLETED"
    assert row["num_chunks"] == 3
    assert row["error"] is None
