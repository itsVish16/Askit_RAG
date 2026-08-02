"""Tests for app/ingest_worker/repo.py — idempotent Qdrant point_id.

Goal: prove the (user_id, sha256, chunk_index) → UUID mapping is stable
(same inputs => same UUID) and sensitive to each input independently.
This is the entire correctness contract that makes SQS at-least-once
redelivery a no-op for already-ingested chunks.
"""
from app.ingest_worker.repo import chunk_ids, deterministic_point_id


def test_deterministic():
    a = deterministic_point_id("u1", "sha", 0)
    b = deterministic_point_id("u1", "sha", 0)
    assert a == b


def test_sensitive_to_user_id():
    assert deterministic_point_id("u1", "sha", 0) != deterministic_point_id("u2", "sha", 0)


def test_sensitive_to_sha():
    # Re-uploading a changed version of the SAME logical PDF should map to
    # different point_ids so we don't silently overwrite the old chunks.
    assert deterministic_point_id("u1", "sha_old", 0) != deterministic_point_id("u1", "sha_new", 0)


def test_sensitive_to_chunk_index():
    # Every chunk in the PDF must land on its own point_id.
    assert deterministic_point_id("u1", "sha", 0) != deterministic_point_id("u1", "sha", 1)


def test_returns_valid_uuid_string():
    import uuid
    for i in range(3):
        u = uuid.UUID(deterministic_point_id("u1", "sha", i))
        assert str(u) == deterministic_point_id("u1", "sha", i)


def test_chunk_ids_length_and_alignment():
    ids = chunk_ids("u1", "sha", 5)
    assert len(ids) == 5
    # No duplicates within one PDF's vector
    assert len(set(ids)) == 5
    for i, expected in enumerate(ids):
        assert deterministic_point_id("u1", "sha", i) == expected
