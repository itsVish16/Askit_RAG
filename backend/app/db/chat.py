"""SQLite-backed chat history store. Same connection pattern as users.py and
ingest status.py: module-level lock-protected singleton, check_same_thread=False
for cross-thread access from both FastAPI handlers and the background flush thread.

Messages are buffered and flushed periodically (every 60 s) so N fast turns in
a row batch into one write window. Sessions are written immediately.
"""

import json
import os
import sqlite3
import threading
import time

from app.config import settings

# --- Schema ---

_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    title       TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('human', 'ai')),
    content     TEXT NOT NULL,
    context     TEXT DEFAULT '[]',      -- JSON list of context chunks
    queries     TEXT DEFAULT '[]',      -- JSON list of tool queries
    keywords    TEXT DEFAULT '[]',      -- JSON list of BM25 keywords
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

# --- Connection (same pattern as users.py / status.py) ---

_conn: sqlite3.Connection | None = None
_conn_lock = threading.Lock()
_conn_initialized = False


def _get_db_path() -> str:
    return os.getenv("CHAT_DB_PATH", os.path.join(settings.INGEST_UPLOAD_DIR, "..", "chat.sqlite"))


def _init_db() -> None:
    global _conn, _conn_initialized
    if _conn_initialized:
        return
    with _conn_lock:
        if _conn_initialized:
            return
        path = os.path.abspath(_get_db_path())
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_SQL)
        _conn.commit()
        _conn_initialized = True


def _get_conn() -> sqlite3.Connection:
    if not _conn_initialized:
        _init_db()
    return _conn


# --- Message buffer + periodic flush ---

_pending: list[dict] = []
_pending_lock = threading.Lock()
_FLUSH_INTERVAL = 15  # seconds


def queue_message(
    session_id: str,
    role: str,
    content: str,
    context: list[str] | None = None,
    queries: list[str] | None = None,
    keywords: list[str] | None = None,
) -> None:
    """Add a message to the in-memory buffer. The flush thread persists it."""
    with _pending_lock:
        _pending.append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "context": json.dumps(context or []),
                "queries": json.dumps(queries or []),
                "keywords": json.dumps(keywords or []),
            }
        )


def flush() -> int:
    """Write all buffered messages to SQLite. Returns count of messages flushed."""
    global _pending
    with _pending_lock:
        batch = _pending
        _pending = []
    if not batch:
        return 0
    conn = _get_conn()
    conn.executemany(
        "INSERT INTO messages (session_id, role, content, context, queries, keywords) "
        "VALUES (:session_id, :role, :content, :context, :queries, :keywords)",
        batch,
    )
    conn.commit()
    return len(batch)


def flush_loop() -> None:
    """Daemon thread target. Every FLUSH_INTERVAL seconds, persists buffered messages."""
    while True:
        time.sleep(_FLUSH_INTERVAL)
        try:
            n = flush()
            if n:
                print(f"  [chat] flushed {n} messages")
        except Exception as exc:
            print(f"  [chat] flush failed: {type(exc).__name__}: {exc}")


# --- Session CRUD ---


def create_session(session_id: str, user_id: str, title: str = "") -> dict | None:
    """INSERT OR IGNORE a session row. Returns the row on success, None if exists."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, user_id, title) VALUES (?, ?, ?)",
        (session_id, user_id, title),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def update_session_title(session_id: str, title: str) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
        (title, session_id),
    )
    conn.commit()


def get_sessions_by_user(user_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def delete_session(session_id: str, user_id: str) -> bool:
    """Delete a session AND its messages. Returns True if a row was deleted."""
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


# --- Message CRUD ---


def get_messages(session_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def message_count(session_id: str) -> int:
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row["cnt"] if row else 0
