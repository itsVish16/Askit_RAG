# Bugs

Status legend: ✅ Resolved (in code) | ⚠️ Open | 🔍 Needs investigation

## Critical Bugs

### 1. Missing Error Handling in Qdrant Retrieval — ✅ Resolved
**Location:** `backend/app/db/retrievers.py` (`_scroll_with_retry`, `_dense_safe`)
**Fix:** Qdrant scroll now retries with exponential backoff + full-jitter (5xx,
429, network errors); fail-fast on 4xx. Dense retrieval wrapped so a Qdrant
outage returns `[]` (degraded) instead of killing the request. BM25 cache
stores `None` on unreachable Qdrant → dense-only fallback.

### 2. No Input Validation on User Query — ✅ Resolved
**Location:** `backend/app/api/ask.py` (`UserInput`, `_check_rate_limit`)
**Fix:** `query` capped at `MAX_QUERY_LEN=4096`; NUL/DEL/control bytes stripped
(`\n` kept); per-session sliding-window rate limit (`MAX_RPM_PER_SESSION=30`,
HTTP 429).

### 3. Cross-Encoder Crash on Import — ✅ Resolved
**Location:** `backend/app/db/retrievers.py` (`get_reranker`)
**Fix:** Reranker loads lazily on first use, caches `None` on failure.
`rerank_texts` falls back to "first `k_final` in pool order" — worse answers,
but the request still completes.

---

## Medium Priority Bugs

### 4. BM25 Index Rebuilt Per `k` Value — ⚠️ Open (by design)
**Location:** `backend/app/db/retrievers.py` (`_bm25_cache` keyed by `k`)
**Note:** Cache is keyed by `k`. The app uses a single `K_RETRIEVE`, so in
practice one build happens. Multiple `k` values would re-scroll. Acceptable
for the single-process educational deployment; revisit if `k` becomes variable.

### 5. Redundant Retrievals in Multi-Query Node — ⚠️ Open
**Location:** `backend/app/agent/nodes.py` (`retrieve_node`)
**Note:** Each multi-query variant queries Qdrant + BM25 independently;
overlapping results are deduped after. Sequential `asyncio.gather` over
variants would cut latency — tracked in `suggestions.md` #8.

### 6. No Logging Configuration — ⚠️ Open
**Location:** Throughout (`print()` instead of `logging`)
**Note:** No structured logging / correlation IDs. Tracked in `suggestions.md` #3.

### 7. Missing `.env.example` File — ✅ Resolved
**Location:** `.env.example` (checked in; `.env` gitignored)
**Fix:** Every env var the project reads, grouped Required vs Optional.

---

## Low Priority Bugs

### 8. Empty Context Guarded Only by Prompt Text — ⚠️ Open
**Location:** `backend/app/agent/nodes.py` (`generate_node`)
**Note:** When retrieval returns nothing, the LLM prompt's rule (3) refuses
answering. No programmatic early-exit/logging yet. Tracked in `tasks.md` 8.4.

### 9. Hardcoded Prompt Registry — ⚠️ Open (low value)
**Location:** `backend/app/core/prompts.py` (`PROMPT_SPECS`)
**Note:** Registry must stay in sync with prompt definitions manually. Three
prompts only; defer until it grows.

---

## Investigation Needed

### 10. Reranker Cache Directory Permissions — 🔍 Needs Investigation
**Location:** `backend/Dockerfile` (`HF_HOME=/models/huggingface`, `VOLUME /models`)
**Note:** On-device reranker (sentence-transformers) downloads to the HF cache;
the Docker image points it at a mounted `/models` volume. Verify on a read-only
container filesystem. (Embeddings now come from the Fireworks API — no local
embedding cache.)

### 11. Qdrant Timeout Monitoring — 🔍 Needs Investigation
**Location:** `backend/app/config.py` (`QDRANT_TIMEOUT=60`), `backend/app/db/ingestion.py`
(recursive halving)
**Note:** No metric/alert tracks how often timeouts happen. Add when metrics
land (`suggestions.md` #14).

---

*Last Updated: 2026-08-01*
