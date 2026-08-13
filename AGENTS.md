# Project Context: Askit RAG Agent

## 📖 Overview
Askit is a highly scalable, observable, general-purpose RAG (Retrieval-Augmented Generation) API. It allows users to query documents using an agentic workflow powered by LangGraph, rather than a linear chain. The focus of this project is on production-grade engineering: incorporating LLM observability, automated evaluations (LLM-as-a-judge), and scalable vector database architecture.

## 🛠️ Technology Stack
- **Web Framework:** FastAPI
- **AI Orchestration:** LangChain & LangGraph
- **Vector Database:** Qdrant (Currently running in local persistent disk mode)
- **LLM & Embeddings Provider:** Fireworks AI (Using `ChatOpenAI` and `OpenAIEmbeddings` wrappers)
- **Reranker:** on-device `cross-encoder/ms-marco-MiniLM-L6-v2` (sentence-transformers)
- **Observability & Evals:** Opik (by Comet) for tracing and metric evaluation
- **Auth:** bcrypt + JWT, sqlite users store
- **Frontend:** Next.js 15 (App Router) + Tailwind (`frontend/`)
- **Package Management:** `uv`

## 🏗️ Repository Layout
- `backend/` — the FastAPI + LangGraph API (run all `uv` commands from here)
  - `backend/app/main.py` — FastAPI app, lifespan, CORS, router registration
  - `backend/app/agent/` — LangGraph state, nodes, compiled graph
  - `backend/app/api/` — routers: ask, ingest, health, auth, eval (+ auth deps)
  - `backend/app/core/` — llm (+ vision_llm), embeddings, vision, prompts, redact, security
  - `backend/app/db/` — qdrant, retrievers, loaders, ingestion, users
  - `backend/app/queue/` — SQS wrapper + sqlite job status
  - `backend/app/ingest_worker/` — worker LangGraph + daemon-thread runner
  - `backend/app/evaluation/` — evals harness + results cache
  - `backend/tests/` — pytest suite
- `frontend/` — Next.js dashboard (login/register, Experiment, Documents, Ask)

## 🏗️ Architecture & Core Components

### 1. Data Ingestion (`backend/app/db/ingestion.py` + `backend/app/db/loaders.py`)
- **Loader registry:** dispatches by file extension (pdf/txt/md/png/jpg/jpeg).
- **Vectorization:** Fireworks embeddings via `OpenAIEmbeddings`.
- **Storage:** Inserts vectors into a `QdrantVectorStore` and saves them to Qdrant Cloud.
- **Vision fallback:** scanned PDF pages (sparse text) rendered to PNG (PyMuPDF) and sent to a Fireworks vision model when `FIREWORKS_VISION_MODEL_NAME` is set.
- **Async pipeline:** `POST /ingest/pdf` (auth-required) spools the file, publishes a pointer to SQS; a daemon-thread worker (`backend/app/ingest_worker/`) chunk+embed+upserts. Per-user cap: 5 PDFs, ≤10 pages each.

### 2. The Agent Workflow (`backend/app/agent/` + `backend/app/api/ask.py`)
- **State Machine:** Built using LangGraph. The memory/state is tracked via a `GraphState` TypedDict containing `question`, `queries`, `keywords`, `context`, `answer`, `user_id`, `chat_history`.
- **Nodes:** `multi_query` (LLM rewrites into N variants), `keywords` (LLM extracts BM25 terms), `retrieve` (dense ∪ BM25 candidate pool → cross-encoder rerank → top K), `generate` (grounded answer with chat history).
- **API Endpoint:** `POST /ask` (auth-required, retrieval scoped to the logged-in user's documents).
- **Tracing:** Every invocation is wrapped in an `OpikTracer` callback.

### 3. Automated Evaluations (`backend/app/evaluation/evals.py`)
- Implements the **LLM-as-a-Judge** paradigm.
- Uses Opik's `Hallucination`, `AnswerRelevance`, `ContextRecall`, `ContextPrecision` metrics.
- Persists the per-metric averages to `backend/app/evaluation/results.py` (sqlite) so `GET /eval/results` can serve them to the frontend.

### 4. Auth (`backend/app/api/auth.py`, `backend/app/db/users.py`, `backend/app/core/security.py`)
- name + email + password (bcrypt), JWT bearer tokens. `/ask` and `/ingest/*` require auth; `user_id` is forced from the JWT.

## 🗺️ Roadmap & Current Phase

- [x] **Phase 1:** Core RAG Implementation.
- [x] **Phase 2:** Observability & Metrics (Opik Traces, Automated Evals).
- [x] **Phase 3:** Vector DB Migration (Qdrant + BGE/MiniLM, Opik-tuned params).
- [x] **Phase 3.5:** Prompt Versioning.
- [x] **Phase 4:** Scalable Ingestion Pipeline (SQS + in-process worker).
- [x] **Phase 4.5:** Auth, Fireworks API embeddings, vision model, Next.js frontend.
- [ ] **Phase 5:** Production Deployment (Dockerization done; Cloud Qdrant + K8s next).

## 🤖 Rules for AI Assistants

When contributing to this codebase, you must adhere to the following rules:

1. **Pedagogical Explanation First:** This is an educational project for interview preparation. Before writing any code, you MUST explain the *Intuition* and the *Theory/Math* behind the component you are about to build.
2. **Do Not Auto-Edit Files:** Do not use automated tools to overwrite the user's files unless explicitly instructed. Provide the code in the chat, explain it line-by-line, and allow the user to implement it.
3. **Trace Everything:** Any new LangGraph nodes or LLM calls must be integrated with the Opik tracer. We value observability over raw speed.
4. **Agentic over Linear:** If a new feature requires complex logic (e.g., self-correction, web search fallback), implement it as a new Node in the LangGraph workflow with Conditional Edges, rather than forcing it into a linear chain.
5. **Base URL Awareness:** Be mindful of the "Base URL Trap". Fireworks AI through LangChain only requires the root base URL (e.g. `https://api.fireworks.ai/inference/v1`) in the `.env` file. Do not append `/embeddings` or `/chat/completions`.
6. **Backend lives in `backend/`:** All `uv` / `pytest` / `ruff` commands run from `backend/`. The frontend is a separate app in `frontend/`.
