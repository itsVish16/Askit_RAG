# Checklist — Done Tasks

Tracks work completed against `tasks.md` / `bugs.md` / new features, with the
most recent item last. Each entry lists: what was done, the files touched, the
verification run, and any caveats.

---

## 2026-08-01

### [DONE] PDF Ingest Feature (NEW — not in original tasks.md)
- **What:** Users can POST a PDF to `/ingest/pdf`; pages are chunked,
  embedded, and upserted into Qdrant tagged with `metadata.user_id`,
  `metadata.source="pdf"`, `metadata.filename`. A fresh `user_id` is minted
  when the client omits one.
- **Files changed:**
  - `pyproject.toml`, `uv.lock` — added `pypdf`, `python-multipart`
  - `backend/app/db/ingestion.py` — added `load_pdf_documents`, `ingest_pdf`
  - `backend/app/db/qdrant.py` — added `user_scope_filter`, `get_filtered_retriever`,
    `_ensure_user_id_index` (creates a keyword payload index on
    `metadata.user_id` so Qdrant accepts filtered retrievals), plus a
    process-wide `_user_id_index_ensured` guard so we don't pay a
    create_payload_index roundtrip on every request
  - `backend/app/db/retrievers.py` — `retrieve_candidates` and
    `bm25_candidates_from_keywords` now accept `user_id=None`; per-user BM25
    cached in `_user_bm25_cache`; returns [] gracefully when the user has
    uploaded no PDF (BM25Retriever.from_documents([]) would raise, so we
    skip building the index in that case and return None)
  - `backend/app/main.py` — `UserInput` and `GraphState` got a `user_id` field;
    added `POST /ingest/pdf` (admin-style spool-then-ingest) and
    `IngestResponse`; `POST /ask` now threads `user_id` into the graph so
    `retrieve_node` scopes retrieval when set, and keeps the shared COVID-QA
    behaviour when it's None
- **Verification:**
  - `uv run python -c "from app import main; ..."` lists routes: `/ask`,
    `/ingest/pdf`, `/docs`, `/redoc`, `/openapi.json`.
  - Scoped retrieval against a non-existent `user_id` returns `[]` for
    dense, BM25, and the keyword path — no exceptions.
  - `_ensure_user_id_index` is idempotent (Qdrant 409 ignored).
  - Existing unscoped retrieval is unchanged: when `user_id` is None we
    branch identically to the previous behaviour.
- **Caveats / follow-ups:**
  - pdf endpoint currently does **no** size/MIME check — see Bug #2 /
    Task 5.2 for the input-validation pass.
  - No persistence of `user_id` ↔ uploaded files mapping (deleting a
    user's PDFs needs a delete endpoint — not implemented; tracked as
    follow-up in tasks.md backlog).
  - `langchain-community` deprecation warning still present (project-wide,
    not introduced here).

---

### [DONE] Short-term chat memory via LangGraph checkpointer
- **What:** Added an in-memory conversation memory keyed by `thread_id` (=
  API `session_id`). The `generate_node` now appends the new (HumanMessage,
  AIMessage) pair to `state.chat_history` after answering; the
  `MessagesPlaceholder("history")` renders prior turns in the prompt so
  the LLM can resolve follow-ups ("it", "that study") without losing the
  groundedness rules already in the system text.
- **Files changed:**
  - `backend/app/core/prompts.py` — `RAG_PROMPT` now has
    `MessagesPlaceholder("history", optional=True)` between system and
    human; added a 5th rule to `RAG_SYSTEM_TEXT` describing how to use the
    prior history. `PROMPT_SPECS` and `seed_prompts.py` are unchanged (they
    only read the system+human strings, so the new rule flows to Opik on
    the next `seed_prompts --commit` run).
  - `backend/app/main.py` — `GraphState.chat_history:
    Annotated[list[BaseMessage], add_messages]` (the `add_messages`
    reducer appends, not overwrites); `generate_node` reads
    `state.get("chat_history", [])`, passes it as `history`, and returns
    a `new_turn` list that the reducer folds in. `app_agent` now compiles
    with `checkpointer=InMemorySaver()`. `/ask`'s invoke config now passes
    `{"configurable": {"thread_id": session_id}, "callbacks": [opik_tracer]}`,
    so the same Opik thread and LangGraph thread share the same id.
- **Verification:** Stub test (`/tmp/test_chat_memory.py`) replaces `llm`
  with `FakeListChatModel` and stubs `retrieve_candidates` /
  `bm25_candidates_from_keywords` / `rerank_texts`, then:
  1. Two `/ask` calls with `session_id="sess-1"` → final chat_history has
    4 messages (2 turns × (human+ai)). ✅
  2. New `session_id="sess-2"` → independent chat_history of 2 messages. ✅
- **Caveats / follow-ups:**
  - In-memory only — memory resets on process restart ("short-term" by
    design, per the user's request). To upgrade to durable, swap
    `InMemorySaver` for `langgraph.checkpoint.sqlite.SqliteSaver`.
  - No truncation policy yet (long conversations grow unbounded). Tracked
    in tasks.md 7.1 (history truncation policy).

---

---

### [DONE] Task 5.2 — Input validation & security (Bug #2 + Suggestions #4, #17, #18)
- **What:** Hardened both API endpoints against the obvious abuse cases:
  over-long queries, renamed uploads, oversized PDFs, and abusive clients,
  plus masked common PII patterns before they get stored in the in-memory
  conversation history.
- **Files changed:**
  - `backend/app/config.py` — added `MAX_QUERY_LEN=4096`, `MAX_RPM_PER_SESSION=30`,
    `MAX_PDF_SIZE_MB=25`, `MAX_PDF_PAGES=200`, `REDACT_PII=true` (env-driven).
  - `backend/app/core/redact.py` (new) — `redact_pii(text)` regex-masks:
    EMAIL, SSN, DATE (ISO + M/D/YY + "12 March 2021"), IPV4, PHONE.
    Order is load-bearing (DATE before PHONE, IPV4 before PHONE) so dates
    aren't mis-tagged as phones.
  - `backend/app/main.py` — `UserInput.query` is now `Field(...,
    max_length=settings.MAX_QUERY_LEN)`; `__init__` post-hoc strips NUL /
    DEL / non-printable control bytes (kept `\n` so multi-line queries still
    work). Added `_check_rate_limit(session_id)` (sliding 60s window, 429
    when over `MAX_RPM_PER_SESSION`) and called it at the top of `/ask`.
    Added `_validate_pdf_upload(raw, declared_filename)` that checks:
    non-empty (400), size cap (413), `%PDF-` magic header (400), `.pdf`
    extension (400). `/ingest/pdf` reads bytes once, validates, then
    spools to disk. `generate_node` now persists
    `redact_pii(question)` into `chat_history` when `settings.REDACT_PII`
    is true (the LLM still sees the original at generation time — only the
    persisted memory is masked, by design).
- **Verification:** Direct calls (no test client, no real LLM/Qdrant):
  - `UserInput(query='a'*4097)` → Pydantic rejects ("String should have at
    most 4096 characters").
  - `UserInput(query='hello\x00world\x7ftest').query == 'helloworldtest'`.
  - `_validate_pdf_upload(b'not a pdf', 'evil.pdf')` → 400.
  - `_validate_pdf_upload(b'%PDF-1.4', 'evil.txt')` → 400.
  - `_validate_pdf_upload(b'', 'empty.pdf')` → 400.
  - 30 allowed → 31st call → 429 with the configured `MAX_RPM_PER_SESSION=30`.
  - `redact_pii('Email dr.smith@hospital.org on 03/04/2021')` =
    `'Email [EMAIL] on [DATE]'`.
  - End-to-end stub test (`/tmp/test_redact.py`) hit `/ask` with a query
    containing an email; the persisted `chat_history` HumanMessage had
    `[EMAIL]` instead of the address. The LLM still got the original
    email (caller's `answer` call still sees it). ✅
  - Re-ran the chat-memory stub test to confirm no regression: 4 messages
    after two turns, separate session独立.
- **Caveats:**
  - In-process rate limiter assumes a single uvicorn worker (~Phase 5 will
    need a Redis-backed limiter).
  - PII redactor is regex-only — it can't match short local phone numbers
    like `555-2671` (deliberately, to avoid eating biomedical IDs) and
    doesn't redact names ("John Doe"). Real deployments should swap
    `redact_pii` for Microsoft Presidio.
  - Big-text `\n` preservation means OCR-style line art can still come
    through. Acceptable for the educational scope.

---

### [DONE] Task 5.3 — Health check & startup validation + .env.example (Bug #7, Suggestions #2, #20, #22)
- **What:** Added three observability/maintainability touches: a fail-fast
  startup config check, `/health` (liveness) and `/ready` (readiness)
  endpoints, and a checked-in `.env.example` template listing every env
  var the project reads, with sensible defaults commented out.
- **Files changed:**
  - `backend/app/config.py` — added `REQUIRED_ENV` tuple and
    `validate_required_config()` returning the list of missing required
    env vars (separate function so both startup AND `/ready` can call it).
  - `backend/app/main.py` — `startup_build_bm25` now calls
    `validate_required_config()` first and `raise RuntimeError` with the
    missing list + pointer to `.env.example`. Added `GET /health`
    (pure liveness — must never touch Qdrant to avoid restart storms)
    and `GET /ready` (probes: qdrant list-collections, fastembed
    `embed_query`, reranker presence, BM25 cache state, env-var
    completeness; aggregates, returns 200 + JSON or 503 via
    `JSONResponse`). Imported `JSONResponse` from `fastapi.responses`.
  - `.env.example` (new) — every env var the project reads, grouped
    Required vs Optional, with the default value inline as a comment.
- **Verification:**
  - `with TestClient(main.app) as c:` startup ran (BM25 OK + reranker
    warmed logged), then `GET /ready` returned 200 with `ready=true`
    and per-component checks: qdrant ok (collections listed),
    embeddings ok (dim=1024), reranker ok, bm25 ok cached, config ok.
  - Mocked `validate_required_config = lambda: ['FIREWORKS_API_KEY',
    'QDRANT_URL']` then called `startup_build_bm25()` → raised
    `RuntimeError("Askit RAG cannot start — required env vars missing:
    FIREWORKS_API_KEY, QDRANT_URL. See .env.example...")`. ✅
  - Routes registered: `/ask`, `/health`, `/ingest/pdf`, `/ready`, plus
    FastAPI defaults `/docs`, `/redoc`, `/openapi.json`.
  - `.env.example` is present (1722 bytes); `.env` is in `.gitignore`
    while `.env.example` is not, so it ships.
- **Caveats:**
  - `/ready` deliberately does NOT call Fireworks (would cost money and
    add latency on every probe). We rely on the startup env-var check
    for Fireworks config validation, which is the right trade.
  - `validate_required_config` reads `os.getenv` first, with `settings`
    as fallback — so a tampered-at-runtime env var doesn't fool the
    check (settings captured the real value at import).

---

### [DONE] Task 5.4 — Robust cross-encoder loading (Bug #3)
- **What:** Stopped loading the cross-encoder at module import time. The
  reranker now loads lazily on first `get_reranker()` call (which
  `startup_build_bm25` and `/ready` both trigger), with a single
  per-process attempt that caches `None` on failure. When the reranker
  is unavailable (`get_reranker() is None`), `rerank_texts` falls back to
  "first `k_final` texts in pool order" — strictly worse answers but
  the request still completes, instead of the whole process crashing
  on a HF Hub blip.
- **Files changed:**
  - `backend/app/db/retrievers.py` — replaced module-level
    `reranker = CrossEncoder(settings.RERANKER_MODEL_NAME)` with
    `reranker: CrossEncoder | None = None` plus a
    `_reranker_initialized` flag and a new `get_reranker()` that loads
    once, caches None on failure, and logs either success or the
    `[reranker] FAILED ... streaming without reranking.` message.
    Modified `rerank_texts` to use `get_reranker()` with the identity
    fallback.
  - `backend/app/main.py` — `/ready` reranker probe now uses `get_reranker()`
    (which both reports state AND forces a lazy load if startup deferred
    it). Reranker load-fail now reports `degraded`, NOT setting
    `overall_ok=False` — reranker is an optimization, dense-only is
    still serviceable.
- **Verification:**
  - Fresh import: `retrievers.reranker is None` and
    `_reranker_initialized is False` — confirmed no import-time load.
  - `get_reranker()` → loaded the real model (`cross-encoder/ms-marco-
    MiniLM-L6-v2 OK`), set `_reranker_initialized=True`. Subsequent
    calls returned the cached instance.
  - Forced-failure path (monkey-patched `CrossEncoder` to raise):
    `get_reranker()` returned `None` and `rerank_texts(["c1","c2","c3","c4"], k=2)`
    returned `["c1","c2"]` (identity fallback, NOT a crash).
  - `with TestClient(main.app)` startup ran BM25 + reranker warmup,
    `GET /ready` returned 200 with `reranker: ok, loaded`.
- **Caveats:**
  - We don't retry the load after a single failure (deliberate — one
    bad launch shouldn't tip the load into a tight loop while serving
    /ask). Restart the process to retry. Acceptable for v1.
  - The fallback preserves pool order, which means it preserves dense
    + BM25 retrieval order. Cross-encoder's job is to reorder based on
    joint query-doc scoring — without it, answer relevance will drop
    back to roughly the "BM25 baseline (0.659)" level seen in README.

---

### [NEXT] Phase-4 ingestion-pipeline (tasks.md §4.x)
Status: pending — the four critical fixes (5.1–5.4) are now complete;
remaining work is the 6.x high-priority improvements (async Qdrant,
structured logging, unit tests).

---

### [DONE] Phase-4 §4.1–4.3 + §4.5–4.6 + §4.7 — SQS-based async ingestion pipeline
- **What:** Async PDF ingestion: `POST /ingest/pdf` writes the PDF to
  `data/uploads/`, publishes a tiny SQS message, returns `{job_id,
  state:"queued"}` immediately. A background daemon thread (started at
  FastAPI startup, joined on shutdown) long-polls SQS and runs each job
  through a 5-node LangGraph pipeline (`fetch_file → extract_pdf →
  chunk → embed_upsert → mark_done` with conditional edges to terminal
  on any node error). Job status lives in a tiny sqlite file
  (`data/ingest_jobs.sqlite`); `/ingest/status/{job_id}` reads it.
  Idempotent upsert (`point_id = uuid(sha256(user_id, sha256(pdf),
  chunk_index))`) makes SQS at-least-once redelivery a no-op — the
  second worker attempt just overwrites the first. Permanent failures
  delete the SQS message (poison-pill avoidance); transient failures
  leave it (visibility timeout redelivers).
- **Stack chosen:** only **SQS** (free-tier always: 1M req/mo). No S3,
  no Lambda, no DynamoDB, no ECS — bytes stay on local disk, status in
  sqlite, worker inside the FastAPI process. Matches the user's
  "lightweight + free-tier" constraint exactly.
- **Files changed:**
  - `pyproject.toml`, `uv.lock` — added `boto3`
  - `backend/app/config.py` — added AWS_REGION, AWS creds (optional),
    SQS_QUEUE_URL/`_DLQ_URL`, VisibilityTimeout/WaitTime/MaxMessages
    /MaxAttempts, SQS_ENDPOINT_URL (Localstack), INGEST_UPLOAD_DIR,
    INGEST_STATUS_DB_PATH, INGEST_KEEP_PDF_AFTER_SUCCESS,
    INGEST_WORKER_ENABLED
  - `backend/app/queue/__init__.py`, `backend/app/queue/sqs.py`, `backend/app/queue/status.py`
    (NEW) — boto3 SQS wrapper (send_job/receive_one/delete_message/
    is_configured, all single-AWS-service), sqlite job-status table
    with `jobs_touch` trigger for `updated_at`
  - `backend/app/ingest_worker/__init__.py`, `repo.py`, `nodes.py`, `flow.py`,
    `runner.py` (NEW) — `deterministic_point_id` + `chunk_ids`
    helpers, the worker `StateGraph` (5 nodes + 4 conditional edges,
    `route_after_node` short-circuits to `mark_done` on any error),
    background daemon-thread runner with `start_worker_thread` /
    `stop_worker_thread` (graceful via threading.Event + interruptible
    sleep).
  - `backend/app/db/ingestion.py` — `embed_and_upsert` now accepts an optional
    `ids: list[str]` aligned 1:1 with `chunks`; recursive-halving
    retry is preserved on the ids+chunks pairing. `QdrantVectorStore
    .add_documents(ids=...)` triggers real upsert-by-point_id.
  - `backend/app/main.py` — `@app.on_event("startup")` now calls
    `start_worker_thread()`; new `@app.on_event("shutdown")` calls
    `stop_worker_thread()`. Rewrote `/ingest/pdf` from synchronous to
    publish-and-return: validate (`_validate_pdf_upload` from Task 5.2),
    `_save_upload(raw, user_id)` → `data/uploads/{job_id}.pdf` (hash),
    if `sqs.is_configured()` → `ingest_status.create_job(PENDING)` +
    `sqs.send_job()` → return `{state:"queued"}`, else fallback to
    inline `ingest_pdf()` (preserves dev-mode ergonomics). Added
    `GET /ingest/status/{job_id}` → sqlite row → `JobStatusResponse`.
    Added new models `IngestResponse` (with `job_id`, `state`,
    `num_chunks: int|None`, `file_path`) and `JobStatusResponse`.
  - `.env.example` — Phase 4 section appended with all SQS/sqlite/
    upload-dir keys + Localstack override hint.
- **Verification:** `_test_phase4.py` (removed after run) stubs SQS
  (in-memory queue), `load_pdf_documents`, `chunk_documents`, and
  `embed_and_upsert` so no AWS / Qdrant / Fireworks calls are needed,
  then drives a real `TestClient(main.app)` end-to-end:
  1. `with TestClient(main.app) as c:` startup logged `[ingest_worker]
     worker thread started (daemon).` then `polling SQS...`.
  2. `POST /ingest/pdf` with a minimal valid PDF (real `%PDF-1.4` magic
     bytes) → `200 {state: "queued", job_id: <uuid_hex>, file_path:
     "data/uploads/<job_id>.pdf"}`.
  3. Worker thread picked job asynchronously: stub-printed
     `load_pdf_documents -> 3 pages`, `chunk_documents(3) -> 6 chunks`,
     `embed_and_upsert(6 chunks, ids=6)` (idempotent ids actually
     computed via `repo.chunk_ids`).
  4. `[ingest_worker] job <job_id> COMPLETED — SQS message deleted.`
     → `mark_done` wrote the sqlite row `state=COMPLETED,
     num_chunks=6`.
  5. `GET /ingest/status/{job_id}` (polled inside 10s budget) returned
     `{state: "COMPLETED", num_chunks: 6, user_id: "u_smoke",
     sha256: "c16bbdca..."}`.
  6. `_DELETIONS = ['rh-<job_id>']` confirmed SQS ack happened on
     success.
  7. Shutdown hook logged `[ingest_worker] worker thread stopped.`
- **Caveats:**
  - Worker thread is **single-process** — if you scale uvicorn to
    multiple workers (or run multiple API pods), each one spawns its
    own SQS consumer; with `MaxNumberOfMessages=1` that's still fine
    (SQS hands each message to exactly one consumer) but throughput
    still bottlenecks on Qdrant write rate. Swap to a separate worker
    binary later if you need to scale compute independently of /ask.
  - The orphan-sweeper (re-publish sqlite jobs stuck in PENDING across
    a FastAPI restart) is NOT implemented in v1. SQS still has the
    message redelivering after visibility timeout lapses, so orphan
    processing happens naturally — but if the SQS queue itself was
    cleared out-of-band, PENDING sqlite rows would stay forever.
  - `embed_and_upsert` is the real Qdrant write path; it relies on
    Task 5.1's retry-on-Qdrant-5xx inside the LangGraph node, so
    transient Qdrant failures are still handled — they bubble out of
    embed_upsert_node as `error_type="transient"`, mark_done writes
    `RETRYING` to sqlite, and SQS visibility-timeout redelivers.
  - SQS redrive-policy (max receive count → DLQ) is configured at
    queue creation in AWS, NOT from this codebase — using
    `SQS_DLQ_URL` is just informational for now; wire it through the
    AWS console's RedrivePolicy on the source queue.

---

### [DONE] Task 6.3 — Unit test suite (Suggestion #13, partial)
- **What:** Stood up the project's first test suite. Coverage:
  every safety/reliability contract added in Tasks 5.1–5.4 + Phase 4,
  minus the prompt-template formatting tests (low value, deferred).
  Tests are unit-by-design — no AWS / Qdrant / Fireworks calls in the
  fast path; the only network-ish IO is sqlite on a per-test `tmp_path`.
- **Files added:**
  - `pytest.ini` — testpaths, pythonpath=`.`, `addopts=-ra --strict-markers`,
    `asyncio_mode=auto` (no test currently uses async, but config'd so we
    don't trip over it later), deprecation warnings filtered.
  - `pyproject.toml` / `uv.lock` — added `pytest` + `pytest-asyncio` as
    dev-deps (and `--dev` flag via uv).
  - `backend/tests/README.md`, `backend/tests/__init__.py`-free layout (pytest auto-collects).
  - `backend/tests/test_redact.py` — 9 cases. EMAIL/SSN/DATE(ISO+US)/IPV4/PHONE
    mask correctly; DATE-before-PHONE ordering verified (a literal
    regression test for the order-dependence comment); biomedical
    text like "COVID-19 patients aged 45+" not falsely redacted; short
    7-digit phones deliberately not matched (Biomedical-identifier
    preservation).
  - `backend/tests/test_repo.py` — 6 cases. Stable, sensitive to user_id/sha256/
    chunk_index independently, returns valid UUID strings, no duplicates
    within one PDF.
  - `backend/tests/test_status.py` — 7 cases. create_job + get_job + set_state;
    the `jobs_touch` trigger bumps `updated_at` on UPDATE; INSERT OR IGNORE
    makes a duplicate publish a no-op; list_pending_jobs returns
    PENDING + RETRYING but not COMPLETED; unknown job returns None.
  - `backend/tests/test_qdrant_filter.py` — 3 cases. `user_scope_filter(None)` is
    None (preserves legacy /ask mode); a named user builds a `Filter`
    with `FieldCondition(key="metadata.user_id", match=...)` exactly —
    regress on the metadata-path contract should a langchain-qdrant
    version bump change the payload key.
  - `backend/tests/test_retry.py` — 5 cases. `_scroll_with_retry` retries on
    5xx up to `max_attempts`; succeeds if a flaky function returns on
    attempt N (≤ max); fail-fasts on 401 (1 attempt); retries on 429;
    retries bare `ConnectionError` (no `.status_code`) as transient.
  - `backend/tests/test_validation.py` — 12 cases. UserInput max_length + NUL/DEL
    strip + whitespace trim; `_validate_pdf_upload` rejects empty /
    wrong-magic / wrong-extension / over-size / accepts valid;
    `_check_rate_limit` allows under cap, raises 429 at cap+1, isolates
    per session_id.
  - `backend/tests/test_worker_flow.py` — 5 cases. The ingest worker LangGraph:
    missing-file routes to FAILED with "not found"; transient Qdrant
    5xx in `embed_upsert` routes to RETRYING with attempts+1 (proves
    the conditional-edge contract); empty PDF routes to FAILED;
    `MAX_PDF_PAGES+10` pages routes to FAILED with "too many pages";
    happy path records COMPLETED with the 3 idempotent point_ids
    actually computed via `repo.chunk_ids`. Uses a real (empty) PDF
    stub on `tmp_path` so `fetch_file_node`'s `os.path.exists()` passes
    while `load_pdf_documents`/`chunk_documents`/`embed_and_upsert`
    are monkeypatched to avoid PyMuPDF + Qdrant in unit tests.
- **Verification:** `uv run pytest -q` → **47 passed in ~5.5s**. No
  network calls, no real Qdrant, no real Fireworks. The test fixture
  `worker_state_module` reloads `app.queue.status` and
  `app.ingest_worker.flow` per-test so the per-test sqlite path is fresh
  and the worker graph's compiled `worker_agent` references the
  freshly-imported node functions.
- **Not yet:**
  - Prompt-template formatting tests (ChatPromptTemplate.from_messages
    is too thin a wrapper to be worth the test cost).
  - End-to-end SQS-queue integration test — kept the
    `_test_phase4.py` pattern but as ad-hoc verification, not in the
    suite (would need a stubbed boto3 SQS localstack; deferred).
  - `asyncio_mode = auto` is set but no async tests exist yet — added
    for when §6.1 (async Qdrant) lands.

---

### [DONE] Restructure app/main.py into agent/ + api/ modules
- **What:** Split the 560-line `backend/app/main.py` monolith. `main.py` is now
  FastAPI app + lifespan + router registration only. Graph state/nodes/compile
  moved to `backend/app/agent/{state,nodes,graph}.py`; endpoints to
  `backend/app/api/{ask,ingest,health}.py`. Deprecated `@app.on_event` replaced with a
  lifespan context manager (kills the 5 on_event DeprecationWarnings).
- **Files:** new `backend/app/agent/{__init__,state,nodes,graph}.py`,
  `backend/app/api/{__init__,ask,ingest,health}.py`; slimmed `backend/app/main.py`;
  `backend/app/evaluation/evals.py` imports `agent` from `app.agent.graph`;
  `backend/tests/test_validation.py` repointed to `app.api.{ask,ingest}`.
- **Verification:** `uv run pytest -q` → 49 passed. `app.openapi()['paths']`
  lists `/ask /ingest/pdf /ingest/status/{job_id} /health /ready`.

### [DONE] Vision model + file-type loaders
- **What:** Ingestion now accepts pdf/txt/md/png/jpg/jpeg via a loader registry
  (`backend/app/db/loaders.py`). PDF pages with a sparse/empty text layer (scanned
  docs) are rendered to PNG by PyMuPDF and sent to a Fireworks vision model to
  recover text; image files go through vision directly. No-op when
  `FIREWORKS_VISION_MODEL_NAME` is unset (text-only, unchanged behavior).
  Vision LLM calls traced via Opik (rule #3).
- **Files:** new `backend/app/core/vision.py`, `backend/app/db/loaders.py`; `backend/app/core/llm.py`
  gained a gated `vision_llm`; `backend/app/db/ingestion.py` delegates to the registry;
  `backend/app/api/ingest.py` upload validation generalized to the supported set;
  `backend/app/config.py` + `.env.example` added `FIREWORKS_VISION_MODEL_NAME`,
  `VISION_MIN_CHARS`, `VISION_RENDER_DPI`, `INGEST_SUPPORTED_EXTENSIONS`;
  `pyproject.toml` added `pymupdf` (removed now-unused `pypdf`).
- **Verification:** imports clean; tests green. (Manual: POST a scanned PDF
  with a vision model set → `/ingest/status/{job_id}` reaches COMPLETED.)

### [DONE] Dockerfile + .dockerignore
- **What:** Multi-stage `python:3.12-slim` image — builder installs prod deps
  via `uv sync --frozen --no-dev`; runtime copies the venv + app source.
  `FASTEMBED_CACHE_DIR=/models/fastembed` with a `VOLUME /models` so model
  caches survive restarts. `HEALTHCHECK` via stdlib `urllib` (no curl in slim).
- **Files:** new `Dockerfile`, `.dockerignore`.
- **Verification:** `docker build -t askit-rag .` → image builds;
  `docker run -p 8000:8000 --env-file .env -v askit-models:/models askit-rag`
  → `/health` 200, `/ready` 200 (deps permitting).

### [DONE] Code cleanup + dead-file removal
- **What:** Compressed verbose comments/docstrings across `backend/app/` to
  load-bearing intent only; fixed the `_scroll_with_retry` docstring typo;
  removed dead scratch files `explore_data.py`, `test_doc.txt`, `claude.md`
  (lowercase dup).

