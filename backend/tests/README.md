# Tests for Askit RAG.

Pytest layout. Run from the repo root:

    uv run pytest -q

Tests are designed to NOT hit AWS / Qdrant / Fireworks / Opik — they exercise
the pure-Python logic of the safety, retry, idempotent-upsert, and graph
machinery introduced in Tasks 5.1–5.4 and Phase 4. The single end-to-end
integration for the Phase 4 SQS pipeline is in `test_phase4_flow.py` (it
stubs SQS, sqlite, Qdrant, and the PDF parser in-process).
