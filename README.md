# Askit RAG

A production-grade biomedical RAG over the **RAGBench COVID-QA** corpus, built
and validated incrementally with [Opik](https://www.comet.com/docs/opik/) experiments.

## Architecture

```
question
   │
   ▼
┌───────────────┐   multi-query expansion: LLM rewrites 1 question
│  multi_query  │   into N=4 domain-aware variants (recall engine)
└───────┬───────┘
        ▼
┌───────────────┐   keyword extraction: entities + scientific
│   keywords    │   synonyms for lexical search (precision engine)
└───────┬───────┘
        ▼
┌───────────────┐   per variant: dense (Qdrant + bge-large) ∪ BM25,
│   retrieve    │   plus keyword-driven BM25 → deduped candidate pool
└───────┬───────┘        → cross-encoder rerank → top-5 chunks
        ▼
┌───────────────┐   grounded answer over the retrieved chunks
│   generate    │
└───────────────┘
```

Every stage was validated with a dedicated Opik experiment (50 test questions
against ground-truth answers):

| Change | ContextRecall | ContextPrecision | AnswerRelevance | Hallucination |
|---|---|---|---|---|
| BM25 baseline (broken Fireworks dense) | 0.354 | — | 0.659 | — |
| + local bge-large embeddings, 850/100 chunks | 0.500 | — | 0.829 | — |
| + two-stage cross-encoder rerank | 0.517 | — | 0.859 | — |
| + multi-query expansion | 0.590 | — | — | — |
| + keyword extraction for BM25 | **0.587** | **0.544** | **0.844** | **0.085** |

Negative results kept in the code comments: `bge-reranker-v2-m3` (568M) scored
*worse* than 22M MiniLM (0.823 vs 0.859 relevance); lexical-only retrieval
collapsed recall to 0.439 — the full stack is load-bearing.

## Stack

- **Serving**: FastAPI + LangGraph (nodes map 1:1 to the boxes above)
- **Vector store**: Qdrant Cloud (cosine), embeddings: Fireworks API
  (`nomic-ai/nomic-embed-text-v1` by default, via `OpenAIEmbeddings`)
- **Lexical**: rank-bm25 built from the Qdrant payloads, cached process-wide
- **Reranker**: `cross-encoder/ms-marco-MiniLM-L6-v2` (on-device,
  sentence-transformers)
- **LLM**: Fireworks (OpenAI-compatible API); optional Fireworks vision model
  for scanned/image PDFs and image uploads
- **Ingestion**: AWS SQS absorbs ingest spikes — files stay on local disk,
  job status in sqlite, a daemon-thread worker inside the FastAPI process
  long-polls the queue (no Redis, no S3, no Lambda)
- **Auth**: name + email + password (bcrypt + JWT), sqlite users store;
  `/ask` and `/ingest/*` require a bearer token, retrieval is scoped to the
  logged-in user's uploaded documents
- **Frontend**: Next.js 15 (App Router) + Tailwind — login/register, COVID-QA
  eval metrics, document upload (5 PDFs / ≤10 pages per user), chat
- **Observability**: Opik — one trace per request with per-node/LLM/retriever
  spans, threads per conversation (`session_id`), versioned prompts

## Setup

```bash
cp backend/.env.example .env   # fill in FIREWORKS_*, QDRANT_*, OPIK_*, JWT_SECRET
cd backend && uv sync
```

Required env: `FIREWORKS_API_KEY`, `FIREWORKS_BASE_URL`, `FIREWORKS_MODEL_NAME`,
`QDRANT_URL`, `QDRANT_API_KEY`, `OPIK_API_KEY`, `OPIK_WORKSPACE`,
`OPIK_PROJECT_NAME`, `JWT_SECRET`. Set `CORS_ORIGINS` to the frontend origin
(default `http://localhost:3000`). Run all `uv` / `pytest` / `ruff` commands
from `backend/`.

Data: place the RAGBench COVID-QA parquets under `backend/data/ragbench/covidqa/`
(train/test splits; paths configurable via `INGEST_PARQUET_PATH` / `EVAL_PARQUET_PATH`).

### 1. Ingest the train split into Qdrant

```bash
uv run python -m app.db.ingestion
```

Embeds the COVID-QA train split with the configured Fireworks embedding model
and upserts into Qdrant. **Re-run this whenever you change `EMBEDDING_MODEL_NAME`**
— a different embedding dim needs a new collection (set a new `QDRANT_COLLECTION`).

### 2. Serve the API

```bash
uv run uvicorn app.main:app --port 3001 --reload
```

The API is auth-protected. Register + log in to get a JWT:

```bash
curl -X POST localhost:3001/auth/register -H 'Content-Type: application/json' \
     -d '{"name":"Ada","email":"ada@example.com","password":"password123"}'
# → {"token":"...", "user":{...}}

curl -X POST localhost:3001/ask -H 'Authorization: Bearer <token>' \
     -H 'Content-Type: application/json' -d '{"query":"How is SARS-CoV-2 transmitted?"}'
```

`/ask` retrieval is scoped to the logged-in user's uploaded documents. Send the
same `session_id` on follow-ups to share short-term chat memory.

### 3. Evaluate (test split, 50 questions) — populates the UI's Experiment tab

```bash
uv run python -m app.evaluation.evals
```

Writes metrics + traces to Opik **and** caches the per-metric averages to
`backend/data/eval.sqlite`, which `GET /eval/results` serves to the frontend.

### 4. Version the prompts in Opik

```bash
uv run python -m scripts.seed_prompts --commit
```

## Frontend

Next.js 15 + Tailwind, in `frontend/`.

```bash
cd frontend
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:3001
npm install
npm run dev                  # http://localhost:3000
```

Pages: `/login`, `/register`, and a protected dashboard with three tabs —
**Experiment** (cached COVID-QA metrics), **Documents** (upload + status,
5 PDFs / ≤10 pages per user), **Ask** (chat grounded on your documents).

## Ingestion & file types

`POST /ingest/pdf` (auth-required) accepts `pdf`, `txt`, `md`, `png`, `jpg`,
`jpeg` (`INGEST_SUPPORTED_EXTENSIONS`). It validates, spools the bytes to
`data/uploads/{job_id}.<ext>`, and either:

- **SQS configured** (`SQS_QUEUE_URL` + `INGEST_WORKER_ENABLED=true`): writes a
  PENDING sqlite row, publishes a tiny pointer message to SQS, returns
  `{state: "queued"}` immediately. The worker thread chunk+embed+upserts async.
- **No SQS** (local dev): falls back to inline ingest and returns the result.

Per-user cap: at most `MAX_PDFS_PER_USER=5` completed documents, each
`MAX_PDF_PAGES=10` pages. A 6th upload returns 409; an oversized file fails in
the worker. List your uploads with `GET /ingest/jobs`; poll one with
`GET /ingest/status/{job_id}` (owner-only).

**Vision extraction** — when `FIREWORKS_VISION_MODEL_NAME` is set, PDF pages
with a sparse/empty text layer (scanned docs) are rendered to PNG (PyMuPDF) and
sent to the Fireworks vision model to recover text before chunking; image files
go through the vision model directly. With it unset, ingestion is text-only.
Idempotent Qdrant upserts (`point_id =
uuid(sha256(user_id|sha256(file)|chunk_index))`) make SQS at-least-once
redelivery a no-op.

## Deploy

Backend (FastAPI on :3001) + frontend (Next.js on :3000):

```bash
# backend
cd backend && docker build -t askit-rag .
docker run --rm -p 3001:8000 --env-file ../.env -v askit-models:/models askit-rag

# frontend
cd frontend && docker build -t askit-frontend .
docker run --rm -p 3000:3000 -e NEXT_PUBLIC_API_URL=http://localhost:3001 askit-frontend
```

- Backend: multi-stage `python:3.12-slim`, prod deps only. Mount `/models` for
  the on-device reranker cache (`HF_HOME=/models/huggingface`).
- Frontend: `node:22-slim`, `output: standalone`.
- Health: `GET /health` (liveness, no deps) and `GET /ready` (probes Qdrant,
  embeddings, reranker, BM25, env config → 503 if any down).
- Bring your own Qdrant Cloud + SQS via the `.env` file; set `CORS_ORIGINS` to
  the frontend origin.

## Project layout

```
backend/
  app/
    config.py            # every tunable knob, env-overridable
    main.py              # FastAPI app + lifespan + CORS + router registration
    agent/               # LangGraph: state, nodes, compiled graph
    api/                 # routers: ask, ingest, health, auth, eval + deps
    core/                # llm (+ vision_llm), embeddings, vision, prompts, redact, security
    db/                  # qdrant, retrievers, loaders, ingestion, users (sqlite)
    queue/               # SQS wrapper + sqlite job status
    ingest_worker/       # worker LangGraph + daemon-thread runner
    evaluation/          # evals harness + results cache (sqlite)
  scripts/seed_prompts.py  # push prompts to Opik prompt library
  tests/                 # pytest suite (no AWS/Qdrant/Fireworks in the fast path)
  Dockerfile             # backend image
frontend/                # Next.js 15 app: login/register/dashboard (Experiment, Documents, Ask)
  Dockerfile             # frontend image
```
