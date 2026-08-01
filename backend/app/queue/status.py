"""Sqlite-backed job status for the ingest pipeline.

Single-process deployment = single writer, so thread-safety matters but
distributed coordination doesn't — sqlite + a threading.Lock is enough.

States:
  PENDING    — request accepted; not yet dequeued
  PROCESSING — worker has the SQS message in flight
  COMPLETED  — chunks upserted to Qdrant, SQS msg deleted
  FAILED     — permanent failure (bad PDF, extraction error); SQS msg deleted
  RETRYING   — transient failure (Qdrant 5xx, network blip); SQS msg NOT
               deleted; visibility timeout redelivers. attempts bumped.
"""

import os
import sqlite3
import threading
from typing import Any

from app.config import settings

_conn = None
_conn_lock = threading.Lock()
_initialized = False


def _connect() -> sqlite3.Connection:
    """Open the connection lazily with check_same_thread=False — the ingest
    worker thread writes and the FastAPI handler threads read."""
    global _conn, _initialized
    if _initialized:
        return _conn
    with _conn_lock:
        if _initialized:
            return _conn
        os.makedirs(os.path.dirname(settings.INGEST_STATUS_DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(settings.INGEST_STATUS_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init_db(_conn)
        _initialized = True
        return _conn


def _init_db(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id      TEXT PRIMARY KEY,
            user_id     TEXT,
            file_path   TEXT,
            sha256      TEXT,
            state       TEXT NOT NULL DEFAULT 'PENDING',
            attempts    INTEGER NOT NULL DEFAULT 0,
            num_chunks  INTEGER,
            error       TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    # Auto-update updated_at on every UPDATE.
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS jobs_touch
        AFTER UPDATE ON jobs
        BEGIN
            UPDATE jobs SET updated_at = datetime('now') WHERE job_id = OLD.job_id;
        END
        """
    )
    conn.commit()


def create_job(job_id: str, user_id: str, file_path: str, sha256: str) -> None:
    """Insert a PENDING row. INSERT OR IGNORE keeps a duplicate publish
    idempotent — we keep the first state and don't bump attempts."""
    conn = _connect()
    with _conn_lock:
        conn.execute(
            "INSERT OR IGNORE INTO jobs (job_id, user_id, file_path, sha256) VALUES (?, ?, ?, ?)",
            (job_id, user_id, file_path, sha256),
        )
        conn.commit()


def set_state(
    job_id: str,
    state: str,
    *,
    attempts: int | None = None,
    num_chunks: int | None = None,
    error: str | None = None,
) -> None:
    """Atomic state transition. Each commit marks SQS progress persistently
    (a crash mid-state-machine restarts from the last committed state)."""
    conn = _connect()
    fields = ["state = ?"]
    values: list[Any] = [state]
    if attempts is not None:
        fields.append("attempts = ?")
        values.append(attempts)
    if num_chunks is not None:
        fields.append("num_chunks = ?")
        values.append(num_chunks)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    values.append(job_id)
    with _conn_lock:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", values)
        conn.commit()


def get_job(job_id: str) -> dict | None:
    conn = _connect()
    with _conn_lock:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_pending_jobs(limit: int = 1000) -> list[dict]:
    """Jobs stuck in PENDING/PROCESSING/RETRYING across an API restart — the
    startup sweeper re-sends these to SQS so they get worked again."""
    conn = _connect()
    with _conn_lock:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE state IN ('PENDING','PROCESSING','RETRYING') LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_jobs_by_user(user_id: str) -> list[dict]:
    """All jobs for one user (newest first) — drives the 'My Documents' UI."""
    conn = _connect()
    with _conn_lock:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_user_completed_jobs(user_id: str) -> int:
    """Number of COMPLETED jobs for a user — enforces the per-user PDF cap."""
    conn = _connect()
    with _conn_lock:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE user_id = ? AND state = 'COMPLETED'",
            (user_id,),
        ).fetchone()
    return int(row["n"]) if row else 0
