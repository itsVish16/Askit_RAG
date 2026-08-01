"""Tests for app/db/qdrant.py — pure-logical bits that don't hit Qdrant.

We test only `user_scope_filter` here. The actual client construction
(`QdrantClient(...)`) is module-level in qdrant.py but doesn't perform
any I/O at construction time, so importing the module is safe and does
NOT need AWS/Qdrant Cloud credentials.
"""
from qdrant_client.models import Filter

from app.db.qdrant import user_scope_filter


def test_user_scope_filter_none_when_no_user_id():
    """The contract: when user_id is None/empty, return None so the
    retrieval layer reads the WHOLE shared COVID-QA corpus (the legacy
    /ask behaviour). This is what preserves the Phase-3 default mode."""
    assert user_scope_filter(None) is None
    assert user_scope_filter("") is None


def test_user_scope_filter_for_named_user():
    f = user_scope_filter("u_42")
    assert isinstance(f, Filter)
    # The key path under Qdrant payload is "metadata.user_id" because
    # langchain-qdrant nests each Document's metadata dict under that
    # payload key. If you ever change the langchain-qdrant version, a
    # mismatch here silently widens the scope to the WHOLE collection.
    cond = f.must[0]
    assert cond.key == "metadata.user_id"
    assert cond.match.value == "u_42"


def test_user_scope_filter_distinct_per_user():
    a = user_scope_filter("alice").must[0].match.value
    b = user_scope_filter("bob").must[0].match.value
    assert a == "alice"
    assert b == "bob"
    assert a != b
