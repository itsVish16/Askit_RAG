# Suggestions

Status legend: ✅ Done | ⚠️ Open | 🔍 Needs investigation

## Architecture

### 1. Circuit Breaker for Qdrant — ⚠️ Open
A circuit breaker would fail fast + fall back to BM25-only. The retry layer
(`_scroll_with_retry`) covers transient blips; a true breaker is still worth adding.

### 2. Health Check Endpoint — ✅ Done
`/health` (liveness) + `/ready` (readiness probes Qdrant/embeddings/reranker/BM25/config).

### 3. Structured Logging with Correlation IDs — ⚠️ Open
Replace `print()` with `logging`/`structlog` + Opik trace ID in log context.

### 4. Request Validation with Pydantic — ✅ Done
`UserInput` validates length, strips control bytes, trims whitespace.

---

## Performance

### 5. Async Qdrant Client — ⚠️ Open
Sync retrieval blocks the FastAPI event loop. `qdrant-client` async methods +
a custom async retriever (LangChain `QdrantVectorStore` wraps the sync client).

### 6. BM25 Index Persistence — ⚠️ Open
Persist the BM25 index to disk after first build; invalidate on corpus change.

### 7. Embedding Cache — ⚠️ Open
LRU/Redis cache for repeated embedding results.

### 8. Parallel Multi-Query Retrieval — ⚠️ Open
`asyncio.gather` over multi-query variants (currently sequential — `bugs.md` #5).

---

## Features

### 9. Conversation History Support — ✅ Done
`InMemorySaver` checkpointer keyed by `session_id`; history rendered in the
RAG prompt. ⏳ truncation policy pending.

### 10. Source Citation in Answers — ⚠️ Open
Metadata (doc_id, chunk_index, page) is stored; surface citations in the
prompt + response model.

### 11. Query Classification Node — ⚠️ Open
Route greetings/chit-chat around the full pipeline via a classifier node.

### 12. Feedback Collection Endpoint — ⚠️ Open
`/feedback` POST linked to the Opik trace ID.

---

## Evaluation & Testing

### 13. Unit Tests for Retrieval Functions — ✅ Done
`backend/tests/` (49 passing): redact, repo, status, qdrant filter, retry, validation,
worker flow.

### 14. Load Testing Suite — ⚠️ Open
Locust/k6 scripts for P95 latency, throughput, error rate.

### 15. A/B Testing for Prompt Variants — ⚠️ Open
Prompt-version routing in config; route a % of traffic to experimental prompts.

---

## Security & Compliance

### 16. API Key Rotation Without Restart — ⚠️ Open
Watch env changes or add an admin endpoint to reload config safely.

### 17. PII Redaction in Logs/Traces — ✅ Done
`backend/app/core/redact.py` masks EMAIL/SSN/DATE/IPV4/PHONE before chat_history
persistence. Regex-only (not Presidio) — by design for the educational scope.

### 18. Rate Limiting per Session — ✅ Done
In-process sliding-window limiter keyed by `session_id` (HTTP 429). Needs
Redis for multi-worker (Phase 5).

---

## Deployment & Operations

### 19. Docker Containerization — ✅ Done
Multi-stage `Dockerfile` (python:3.12-slim, uv, `/models` volume, HEALTHCHECK).

### 20. Configuration Validation on Startup — ✅ Done
`validate_required_config()` fail-fast at startup; same check live in `/ready`.

### 21. Graceful Shutdown Handling — ✅ Done
Lifespan context manager stops the ingest worker thread (interruptible sleep)
on shutdown.

---

## Documentation

### 22. Create `.env.example` — ✅ Done

### 23. API Documentation with Examples — ⚠️ Open
Add FastAPI example schemas to `/ask` and `/ingest/pdf`.

### 24. Architecture Decision Records — ⚠️ Open
`docs/adr/` for decisions like "MiniLM over BGE reranker" (currently in comments).

---

*Last Updated: 2026-08-01*
