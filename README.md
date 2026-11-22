<p align="center">
  <img src="docs/assets/Askit_logo.png" alt="Askit Logo" width="260" />
</p>

# Askit RAG

Biomedical document Q&A system built with FastAPI, LangGraph, Qdrant Cloud, Fireworks AI, and Next.js 15, evaluated on the RAGBench COVID-QA benchmark with Opik.

## Architecture

- **Query Pipeline (`backend/app/agent/`):** LangGraph router (`chitchat` / `history` / `rag`) with structured query expansion, hybrid retrieval (Qdrant dense + sparse + BM25), Fireworks cloud reranking (`qwen3-reranker-8b`), and SSE streaming.
- **Ingestion Pipeline (`backend/app/ingest_worker/`):** Async LangGraph worker consuming AWS SQS (or direct local fallback) with PyMuPDF text extraction, Fireworks Vision OCR fallback for scanned pages, deterministic UUID chunk upserts, and per-user `metadata.user_id` isolation.
- **Persistence & Security:** SQLite (`users`, `chat`, `ingest_jobs`, `eval`) with bcrypt password hashing, expiring HS256 JWTs, per-user rate limiting, and regex PII redaction.
- **Observability & Evals (`backend/app/evaluation/`):** Opik tracing across LLM calls and automated COVID-QA evaluation (`Hallucination`, `AnswerRelevance`, `ContextRecall`, `ContextPrecision`).

## Tech Stack

- **Backend:** Python 3.12 (`uv`), FastAPI, LangGraph, Qdrant Cloud, Fireworks AI (LLM, Vision, Embeddings, Reranker), Opik
- **Frontend:** Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS
- **Queue / Storage:** AWS SQS & S3 (optional; falls back to local disk + threadpool)

## Quick Start

### 1. Configure Environment

```bash
git clone https://github.com/itsVish16/Askit_RAG.git
cd Askit_RAG

cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

Set the required variables in `backend/.env`:
- `FIREWORKS_API_KEY`, `FIREWORKS_BASE_URL`, `FIREWORKS_MODEL_NAME`
- `QDRANT_URL`, `QDRANT_API_KEY`
- `OPIK_API_KEY`, `OPIK_WORKSPACE`, `OPIK_PROJECT_NAME`
- `JWT_SECRET`

### 2. Run with Docker Compose

```bash
docker-compose up --build
```

- **Backend API:** `http://localhost:8000`
- **Frontend UI:** `http://localhost:3000`

### 3. Local Development & Tests

```bash
cd backend
uv sync --frozen --python 3.12
uv run uvicorn app.main:app --reload --port 8000

# Run unit tests
uv run pytest -q
```

```bash
cd frontend
npm ci
npm run dev
```

## Evaluation Results (RAGBench COVID-QA, 50-question split)

| Stage | ContextRecall | ContextPrecision | AnswerRelevance | Hallucination |
|---|---|---|---|---|
| BM25 baseline | 0.354 | — | 0.659 | — |
| + Dense embeddings | 0.500 | — | 0.829 | — |
| + Reranker | 0.517 | — | 0.859 | — |
| + Keyword BM25 extraction | **0.587** | **0.544** | **0.844** | **0.085** |
