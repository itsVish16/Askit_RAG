# Tasks

Legend: ⏳ Pending | 🚧 In Progress | ✅ Completed | ❌ Blocked

## Phase 4: Scalable Ingestion Pipeline — ✅ Completed

### 4.1 Decouple Ingestion with Message Queue — ✅
- SQS-based async ingestion (`backend/app/queue/sqs.py`), in-process daemon-thread
  worker (`backend/app/ingest_worker/`). No Redis, no S3, no Lambda — SQS only absorbs
  ingest spikes.

### 4.2 Ingestion API — ✅
- `POST /ingest/pdf` (accepts pdf/txt/md/png/jpg/jpeg), `GET /ingest/status/{job_id}`.

### 4.3 Idempotent Upserts — ✅
- `point_id = uuid(sha256(user_id|sha256(file)|chunk_index))` makes SQS
  at-least-once redelivery a no-op (`backend/app/ingest_worker/repo.py`).
- Document versioning metadata (`ingested_at`) + explicit re-ingest trigger —
  ⏳ pending (low value; deterministic point_id covers the practical case).

---

## Critical Fixes — ✅ Completed

### 5.1 Error Handling in Retrieval — ✅ (`bugs.md` #1)
### 5.2 Input Validation & Security — ✅ (`bugs.md` #2)
- Query length cap, control-byte strip, per-session rate limit, PII redaction
  (`backend/app/core/redact.py`), upload validation (`backend/app/api/ingest.py`).
### 5.3 Health Check & Startup Validation — ✅ (`bugs.md` #7)
- `/health`, `/ready`, `validate_required_config()` fail-fast at startup, `.env.example`.
### 5.4 Robust Cross-Encoder Loading — ✅ (`bugs.md` #3)

---

## High Priority Improvements

### 6.1 Async Qdrant Client — ⏳ Pending (`suggestions.md` #5)
### 6.2 Structured Logging — ⏳ Pending (`bugs.md` #6 / `suggestions.md` #3)
### 6.3 Unit Test Suite — ✅ Completed
- pytest + pytest-asyncio, `backend/tests/` (49 passing, no AWS/Qdrant/Fireworks in
  the fast path). Covers redact, repo, status, qdrant filter, retry,
  validation, worker flow.

### 6.4 Vision Model + File-Type Loaders — ✅ Completed (NEW)
- `backend/app/core/vision.py` (PyMuPDF render + Fireworks vision extraction),
  `backend/app/db/loaders.py` (file-type registry: pdf/txt/md/image). Scanned PDF
  pages fall back to vision when `FIREWORKS_VISION_MODEL_NAME` is set.

### 6.5 Deploy — ✅ Completed (NEW)
- Multi-stage `Dockerfile` (python:3.12-slim, uv, prod deps, `/models`
  volume, `HEALTHCHECK`) + `.dockerignore`.

---

## Medium Priority Features

### 7.1 Conversation History Support — ✅ Completed
- `GraphState.chat_history` + `InMemorySaver` checkpointer keyed by
  `session_id`; `RAG_PROMPT` renders history for follow-up resolution. PII
  redacted before persistence. ⏳ history truncation policy still pending.

### 7.2 Source Citations — ⏳ Pending
### 7.3 Embedding Cache — ⏳ Pending (`suggestions.md` #7)
### 7.4 BM25 Index Persistence — ⏳ Pending (`bugs.md` #4 / `suggestions.md` #6)

---

## Low Priority Enhancements

### 8.1 Docker Containerization — ✅ Completed (see 6.5)
### 8.2 Query Classification — ⏳ Pending (`suggestions.md` #11)
### 8.3 Feedback Collection — ⏳ Pending (`suggestions.md` #12)
### 8.4 Programmatic Empty-Context Guard — ⏳ Pending (`bugs.md` #8)

---

## Backlog (Future Phases)

### Phase 5: Production Deployment
- [ ] Kubernetes manifests (Deployment, Service, HPA)
- [ ] Monitoring dashboards (Grafana/Prometheus)
- [ ] Alerting (PagerDuty/Slack)
- [ ] Blue-green deployment strategy

### Phase 6: Advanced RAG
- [ ] Hybrid search with recency boost
- [ ] Query rewriting for spelling corrections
- [ ] HyDE
- [ ] Document re-ranking with user feedback

### Phase 7: Multi-Tenancy
- [ ] Tenant isolation strategy (separate collections?)
- [ ] Authentication/authorization layer
- [ ] Per-tenant rate limits and quotas
- [ ] Tenant management API

---

## Completed Phases

- **Phase 1:** Core RAG (FastAPI + LangGraph, multi-query, keyword, dense+BM25+rerank, grounded generation)
- **Phase 2:** Observability & Metrics (Opik traces, LLM-as-a-Judge evals)
- **Phase 3:** Vector DB Migration (FAISS→Qdrant Cloud, BGE-large, MiniLM rerank, Opik-tuned params)
- **Phase 3.5:** Prompt Versioning (registry in `prompts.py`, seeded to Opik)

---

*Last Updated: 2026-08-01*
