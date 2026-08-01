"""Sqlite-backed user accounts for auth (name + email + password).

Single-process deployment = single writer, so sqlite + a threading.Lock is
enough (same pattern as app/queue/status.py). Passwords are stored as bcrypt
hashes — never plaintext.
"""

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
        os.makedirs(os.path.dirname(settings.AUTH_DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(settings.AUTH_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init_db(_conn)
        _initialized = True
        return _conn


def _init_db(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def create_user(name: str, email: str, password_hash: str) -> dict:
    """Insert a user. Raises sqlite3.IntegrityError on a duplicate email —
    the API layer maps that to HTTP 409."""
    conn = _connect()
    user_id = uuid.uuid4().hex
    with _conn_lock:
        conn.execute(
            "INSERT INTO users (id, name, email, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, name, email, password_hash),
        )
        conn.commit()
    return get_user(user_id)


def get_user_by_email(email: str) -> dict | None:
    conn = _connect()
    with _conn_lock:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user(user_id: str) -> dict | None:
    conn = _connect()
    with _conn_lock:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None
