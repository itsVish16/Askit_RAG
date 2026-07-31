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
- **Vector store**: Qdrant Cloud (cosine), embeddings: `BAAI/bge-large-en-v1.5`
  (1024-dim, CPU, int8) via fastembed
- **Lexical**: rank-bm25 built from the Qdrant payloads, cached process-wide
- **Reranker**: `cross-encoder/ms-marco-MiniLM-L6-v2`
- **LLM**: Fireworks (OpenAI-compatible API)
- **Observability**: Opik — one trace per request with per-node/LLM/retriever
  spans, threads per conversation (`session_id`), versioned prompts

## Setup

```bash
uv sync
cp .env.example .env   # fill in FIREWORKS_*, QDRANT_*, OPIK_*
```

Data: place the RAGBench COVID-QA parquets under `data/ragbench/covidqa/`
(train/test splits; paths configurable via `INGEST_PARQUET_PATH` / `EVAL_PARQUET_PATH`).

### 1. Ingest the train split into Qdrant

```bash
uv run python -m app.db.ingestion
```

5008 passages → 5198 chunks (850 chars / 100 overlap) → upserted in batches.

### 2. Serve the API

```bash
uv run python -m app.main        # or: uv run uvicorn app.main:app --reload
```

```bash
curl -X POST localhost:8000/ask -H 'Content-Type: application/json' \
     -d '{"query": "How is SARS-CoV-2 transmitted?"}'
# → {"answer": ..., "session_id": ..., "queries": [...], "keywords": [...],
#    "context": [...], "num_candidates": N}
```

Send the same `session_id` on follow-up questions to group them under one
Opik thread.

### 3. Evaluate (test split, 50 questions)

```bash
uv run python -m app.evaluation.evals
```

Writes metrics + traces to the Opik dashboard.

### 4. Version the prompts in Opik

Code is the source of truth for prompt text; push it to Opik's prompt library
so wording changes are tracked as commits:

```bash
uv run python -m scripts.seed_prompts --commit
```

## Project layout

```
app/
  config.py            # every tunable knob, env-overridable
  main.py              # FastAPI app + LangGraph agent
  core/
    llm.py             # ChatOpenAI (Fireworks) + FastEmbed embeddings
    prompts.py         # prompt definitions (source of truth)
  db/
    qdrant.py          # client, collection bootstrap, retriever
    retrievers.py      # BM25 cache, candidate pooling, cross-encoder rerank
    ingestion.py       # parquet → chunks → Qdrant
  evaluation/
    evals.py           # Opik evaluation harness
scripts/
  seed_prompts.py      # push prompts to Opik prompt library
```
