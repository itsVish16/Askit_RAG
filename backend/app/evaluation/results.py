"""Sqlite cache for the latest eval-run metrics (COVID-QA experiment).

evals.py writes here after each `evaluate(...)` run; the API serves the latest
row to the frontend so the UI can display cached results without re-running
the (paid) LLM eval on every page load.
"""

import json
import os
import sqlite3
import threading
import uuid

from app.config import settings

_conn = None
_conn_lock = threading.Lock()
_initialized = False


def _connect() -> sqlite3.Connection:
    global _conn, _initialized
    if _initialized:
        return _conn
    with _conn_lock:
        if _initialized:
            return _conn
        os.makedirs(os.path.dirname(settings.EVAL_DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(settings.EVAL_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init_db(_conn)
        _initialized = True
        return _conn


def _init_db(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_runs (
            id           TEXT PRIMARY KEY,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            metrics_json TEXT NOT NULL
        )
        """
    )
    conn.commit()


def save_eval_results(metrics: dict) -> None:
    """Persist one eval run's metrics (a dict of metric_name -> score)."""
    conn = _connect()
    with _conn_lock:
        conn.execute(
            "INSERT INTO eval_runs (id, metrics_json) VALUES (?, ?)",
            (uuid.uuid4().hex, json.dumps(metrics)),
        )
        conn.commit()


def latest_eval_results() -> dict | None:
    """Return the most recent run as {created_at, metrics: {...}}, or None."""
    conn = _connect()
    with _conn_lock:
        row = conn.execute(
            "SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return {"created_at": row["created_at"], "metrics": json.loads(row["metrics_json"])}
