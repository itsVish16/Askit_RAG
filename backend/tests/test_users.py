"""Tests for app/db/users.py — sqlite users store."""
import importlib
import sqlite3

import pytest


@pytest.fixture
def users_module(tmp_path, monkeypatch):
    db = tmp_path / "users.sqlite"
    monkeypatch.setattr("app.config.settings.AUTH_DB_PATH", str(db))
    import app.db.users as users
    users._conn = None
    users._initialized = False
    importlib.reload(users)
    return users


def test_create_and_get_user(users_module):
    user = users_module.create_user("Alice", "alice@example.com", "hashed")
    assert user["name"] == "Alice"
    assert user["email"] == "alice@example.com"
    assert user["id"]
    fetched = users_module.get_user(user["id"])
    assert fetched["email"] == "alice@example.com"


def test_get_user_by_email(users_module):
    users_module.create_user("Bob", "bob@example.com", "hashed")
    found = users_module.get_user_by_email("bob@example.com")
    assert found is not None and found["name"] == "Bob"
    assert users_module.get_user_by_email("nobody@example.com") is None


def test_email_unique(users_module):
    users_module.create_user("Alice", "alice@example.com", "hashed")
    with pytest.raises(sqlite3.IntegrityError):
        users_module.create_user("Alias", "alice@example.com", "hashed")


def test_get_unknown_user_returns_none(users_module):
    assert users_module.get_user("does-not-exist") is None
