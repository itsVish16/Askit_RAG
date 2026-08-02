"""Tests for app/queue/status.py — sqlite job-status table.

Goal: prove state transitions + the trigger that touches `updated_at` on
every UPDATE work correctly. The status table is the truth-source for
GET /ingest/status/{job_id}, so we lock down its semantics here.

We use a per-test temp file so parallel pytest runs don't trample each
other's rows. We monkeypatch settings.INGEST_STATUS_DB_PATH before
importing the module under test.
"""
import time

import pytest


@pytest.fixture
def status_module(tmp_path, monkeypatch):
    """Force the sqlite db to a per-test temp path, then (re)import the
    status module fresh so its lazy `_connect()` picks up the new path."""
    db = tmp_path / "ingest_jobs.sqlite"
    monkeypatch.setattr("app.config.settings.INGEST_STATUS_DB_PATH", str(db))
    import importlib

    import app.queue.status as status
    # Reset the module-level lazy singleton so a fresh process-state is used
    status._conn = None
    status._initialized = False
    importlib.reload(status)
    yield status
    # Cleanup happens implicitly via tmp_path fixture


def test_create_and_get(status_module):
    status_module.create_job("j1", "u1", "/tmp/foo.pdf", "sha")
    row = status_module.get_job("j1")
    assert row["state"] == "PENDING"
    assert row["user_id"] == "u1"
    assert row["file_path"] == "/tmp/foo.pdf"
    assert row["sha256"] == "sha"
    assert row["attempts"] == 0
    assert row["num_chunks"] is None
    assert row["error"] is None


def test_set_state_completed(status_module):
    status_module.create_job("j1", "u1", "/tmp/foo.pdf", "sha")
    status_module.set_state("j1", "COMPLETED", num_chunks=42)
    row = status_module.get_job("j1")
    assert row["state"] == "COMPLETED"
    assert row["num_chunks"] == 42


def test_set_state_with_attempts_and_error(status_module):
    status_module.create_job("j1", "u1", "/tmp/foo.pdf", "sha")
    status_module.set_state("j1", "RETRYING", attempts=2, error="qdrant 503")
    row = status_module.get_job("j1")
    assert row["state"] == "RETRYING"
    assert row["attempts"] == 2
    assert row["error"] == "qdrant 503"


def test_updated_at_touched_on_state_change(status_module):
    """Verifies the trigger actually bumps updated_at — without the trigger
    we'd need to set updated_at manually in every set_state call."""
    status_module.create_job("j1", "u1", "/tmp/foo.pdf", "sha")
    before = status_module.get_job("j1")["updated_at"]
    # SQLite's default datetime('now') is 1-second resolution.
    time.sleep(1.05)
    status_module.set_state("j1", "PROCESSING")
    after = status_module.get_job("j1")["updated_at"]
    assert before != after, f"updated_at not touched: before={before} after={after}"


def test_create_job_is_idempotent(status_module):
    """INSERT OR IGNORE means a duplicate publish doesn't blow up the row
    or reset attempts/state."""
    status_module.create_job("j1", "u1", "/tmp/foo.pdf", "sha")
    status_module.set_state("j1", "PROCESSING", attempts=1)
    before = status_module.get_job("j1")

    # Second create (e.g. from a duplicate SQS publish) must not erase progress.
    status_module.create_job("j1", "u1", "/tmp/foo.pdf", "sha")
    after = status_module.get_job("j1")

    assert before == after


def test_list_pending_jobs(status_module):
    status_module.create_job("j1", "u1", "/a.pdf", "sha")
    status_module.create_job("j2", "u1", "/b.pdf", "sha")
    status_module.set_state("j2", "COMPLETED", num_chunks=10)
    status_module.create_job("j3", "u2", "/c.pdf", "sha3")
    status_module.set_state("j3", "RETRYING", attempts=1)

    pending = status_module.list_pending_jobs()
    pending_ids = {j["job_id"] for j in pending}
    assert "j1" in pending_ids
    assert "j3" in pending_ids  # RETRYING counts as still-to-process
    assert "j2" not in pending_ids  # COMPLETED is filtered out


def test_get_unknown_job_returns_none(status_module):
    assert status_module.get_job("does_not_exist") is None
