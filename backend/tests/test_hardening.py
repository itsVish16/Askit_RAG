"""Regression tests for security, tenant isolation, and SQLite durability fixes."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from app.api import ask
from app.config import settings
from app.core.security import create_jwt, decode_jwt
from app.db import chat as chat_db


def test_expired_jwt_rejected(monkeypatch):
    monkeypatch.setattr("app.config.settings.JWT_SECRET", "test-secret-key")
    expired = jwt.encode(
        {"sub": "u1", "exp": datetime.now(UTC) - timedelta(seconds=5)},
        "test-secret-key",
        algorithm=settings.JWT_ALG,
    )
    assert decode_jwt(expired) is None


def test_jwt_without_exp_rejected(monkeypatch):
    monkeypatch.setattr("app.config.settings.JWT_SECRET", "test-secret-key")
    no_exp = jwt.encode({"sub": "u1"}, "test-secret-key", algorithm=settings.JWT_ALG)
    assert decode_jwt(no_exp) is None


def test_fresh_jwt_contains_exp(monkeypatch):
    monkeypatch.setattr("app.config.settings.JWT_SECRET", "test-secret-key")
    token = create_jwt("u1", expires_hours=1)
    assert decode_jwt(token) == "u1"


def test_session_ownership_blocks_other_user(tmp_path, monkeypatch):
    db_file = tmp_path / "chat_test.sqlite"
    monkeypatch.setenv("CHAT_DB_PATH", str(db_file))
    monkeypatch.setattr(chat_db, "_conn", None)
    monkeypatch.setattr(chat_db, "_conn_initialized", False)

    chat_db.create_session("sess-owned", "user-a", "Private chat")
    ask._verify_session_ownership("sess-owned", "user-a")

    with pytest.raises(HTTPException) as exc_info:
        ask._verify_session_ownership("sess-owned", "user-b")
    assert exc_info.value.status_code == 404


def test_chat_delete_cascades_messages(tmp_path, monkeypatch):
    db_file = tmp_path / "chat_cascade.sqlite"
    monkeypatch.setenv("CHAT_DB_PATH", str(db_file))
    monkeypatch.setattr(chat_db, "_conn", None)
    monkeypatch.setattr(chat_db, "_conn_initialized", False)
    chat_db._pending.clear()

    chat_db.create_session("sess-1", "user-a", "Test")
    chat_db.queue_message("sess-1", "human", "hello")
    chat_db.flush()
    assert chat_db.message_count("sess-1") == 1

    assert chat_db.delete_session("sess-1", "user-a") is True
    assert chat_db.message_count("sess-1") == 0
