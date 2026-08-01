"""Idempotent-upsert helpers for the ingest worker.

Translate job parameters (user_id, sha256 of the uploaded file, chunk index)
into a deterministic Qdrant point_id that makes SQS redelivery a no-op.
"""

import hashlib
import uuid


def deterministic_point_id(user_id: str, sha256: str, chunk_index: int) -> str:
    """Stable UUID for (user_id, sha256(file), chunk_index). Qdrant point IDs
    must be integers or UUIDs; we hash to 16 bytes and build a UUID. Same
    inputs ⇒ same UUID ⇒ upsert overwrites instead of duplicating.

    chunk_index keeps every chunk on its own point. sha256(file) makes a
    re-upload of a changed file get NEW points (old ones aren't silently
    overwritten). user_id enforces scope even at the storage layer (two users
    uploading the same file never collide)."""
    key = f"{user_id}|{sha256}|{chunk_index}".encode()
    return str(uuid.UUID(bytes=hashlib.sha256(key).digest()[:16]))


def chunk_ids(user_id: str, sha256: str, num_chunks: int) -> list[str]:
    """Build the full id list for a job's chunks in one shot."""
    return [deterministic_point_id(user_id, sha256, i) for i in range(num_chunks)]
