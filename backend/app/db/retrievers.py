import random
import time

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from app.config import settings
from app.db.qdrant import (
    get_filtered_retriever,
    get_retriever,
    qdrant_client,
    user_scope_filter,
)

# Cross-encoder reranker (22M, local CPU). bge-reranker-v2-m3 (568M) scored
# WORSE on answer_relevance (0.823 vs 0.859) at 25x the size — MiniLM wins.
# Lazy + defensive: not loaded at import time. On load failure we cache None
# and rerank_texts falls back to "first k_final in pool order" (no reranking).
reranker: CrossEncoder | None = None
_reranker_initialized: bool = False


def get_reranker() -> CrossEncoder | None:
    """Return the cached cross-encoder, loading on first use. Caches None on
    failure so one bad load never kills more than the first rerank attempt."""
    global reranker, _reranker_initialized
    if _reranker_initialized:
        return reranker
    _reranker_initialized = True
    try:
        reranker = CrossEncoder(settings.RERANKER_MODEL_NAME)
        print(f"  [reranker] loaded {settings.RERANKER_MODEL_NAME} OK.")
    except Exception as exc:
        reranker = None
        print(
            f"  [reranker] FAILED to load {settings.RERANKER_MODEL_NAME}: "
            f"{type(exc).__name__}: {exc} — streaming without reranking."
        )
    return reranker


# BM25 retriever cache: build the keyword index ONCE instead of per-query
# (rebuilding scrolls all ~5k docs from Qdrant on every question). Keyed by k
# for the global index, by user_id for per-user PDF indexes. None entries mean
# "Qdrant unreachable / empty" — callers MUST handle None for both paths.
_bm25_cache: dict[int, BM25Retriever | None] = {}
_user_bm25_cache: dict[str, BM25Retriever | None] = {}


def _scroll_with_retry(scroll_fn, *, max_attempts: int = 4, base_delay: float = 0.5):
    """Retry a Qdrant scroll call. 4xx (except 429) fails fast; 5xx and network
    errors retry with exponential backoff + full-jitter. Returns:
      (True, (points, offset)) on success | (False, exc) on give-up."""
    last_exc = None
    for attempt in range(max_attempts):
        try:
            points, offset = scroll_fn()
            return True, (points, offset)
        except Exception as exc:
            last_exc = exc
            status = getattr(exc, "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                break  # auth/config errors won't fix themselves
            delay = min(8.0, base_delay * (2 ** attempt)) * random.uniform(0.5, 1.0)
            print(
                f"  [qdrant retry] attempt={attempt + 1}/{max_attempts} "
                f"status={status} err={type(exc).__name__}: {exc} — sleeping {delay:.2f}s"
            )
            time.sleep(delay)
    return False, last_exc


def _fetch_all_documents(batch_size: int = 256) -> list[Document]:
    """Scroll the entire collection with retry. Returns [] if Qdrant is
    unreachable after retries — the BM25 cache stores None, callers fall back
    to dense-only retrieval."""
    documents: list[Document] = []
    offset = None

    def call():
        return qdrant_client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=batch_size,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )

    while True:
        ok, result = _scroll_with_retry(call)
        if not ok:
            print(f"  [qdrant] giving up on _fetch_all_documents: {result}")
            return []
        points, offset = result
        for point in points:
            documents.append(
                Document(page_content=point.payload["page_content"], metadata=point.payload.get("metadata", {}))
            )
        if offset is None:
            break
    print(f"Fetched {len(documents)} documents from Qdrant for the BM25 index.")
    return documents


def _fetch_user_documents(user_id: str, batch_size: int = 256) -> list[Document]:
    """Scroll only one user's chunks (filter on metadata.user_id). Same
    retry+fallback as _fetch_all_documents: returns [] on unreachable Qdrant."""
    documents: list[Document] = []
    offset = None
    flt = user_scope_filter(user_id)

    def call():
        return qdrant_client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=batch_size,
            with_payload=True,
            with_vectors=False,
            offset=offset,
            scroll_filter=flt,
        )

    while True:
        ok, result = _scroll_with_retry(call)
        if not ok:
            print(f"  [qdrant] giving up on _fetch_user_documents({user_id}): {result}")
            return []
        points, offset = result
        for point in points:
            documents.append(
                Document(page_content=point.payload["page_content"], metadata=point.payload.get("metadata", {}))
            )
        if offset is None:
            break
    print(f"Fetched {len(documents)} documents for user_id={user_id} (BM25 index).")
    return documents


def get_bm25_retriever(k: int = 3) -> BM25Retriever | None:
    """Cached global BM25 retriever. Returns None (not raise) when the
    collection is empty or Qdrant is unreachable, so callers degrade to
    dense-only. Logs loudly on empty collection — that's a setup problem."""
    if k in _bm25_cache:
        return _bm25_cache[k]
    documents = _fetch_all_documents()
    if not documents:
        print(
            f"  [bm25] no documents for '{settings.QDRANT_COLLECTION}' — Qdrant is empty "
            "(run `uv run python -m app.db.ingestion`) or unreachable. Dense-only fallback."
        )
        _bm25_cache[k] = None
        return None
    retriever = BM25Retriever.from_documents(documents)
    retriever.k = k
    _bm25_cache[k] = retriever
    return retriever


def get_user_bm25_retriever(user_id: str, k: int = 3) -> BM25Retriever | None:
    """Cached per-user BM25 index built from that user's uploaded PDF chunks.
    Returns None when the user has no uploads yet OR Qdrant is unreachable.
    (BM25Retriever.from_documents([]) raises, so we avoid that construction.)"""
    if user_id in _user_bm25_cache:
        return _user_bm25_cache[user_id]
    documents = _fetch_user_documents(user_id)
    if not documents:
        _user_bm25_cache[user_id] = None
        return None
    retriever = BM25Retriever.from_documents(documents)
    retriever.k = k
    _user_bm25_cache[user_id] = retriever
    return retriever


def bm25_candidates_from_keywords(
    keywords: list[str], k: int = 10, user_id: str | None = None
) -> list[str]:
    """BM25 search using extracted domain keywords. Queries with the joined
    string AND each keyword individually to catch multi-term and rare-term
    matches. Scoped to a user's per-user index when user_id is set; returns []
    when that index is None (no uploads / Qdrant down)."""
    if not keywords:
        return []
    if user_id:
        bm25 = get_user_bm25_retriever(user_id, k=k)
        if bm25 is None:
            return []
    else:
        bm25 = get_bm25_retriever(k=k)
        if bm25 is None:
            return []
    candidates: list[str] = []
    for q in [" ".join(keywords), *keywords]:
        candidates.extend(doc.page_content for doc in bm25.invoke(q))
    return list(dict.fromkeys(candidates))  # dedupe, preserve order


def _dense_safe(query: str, k: int, user_id: str | None) -> list[Document]:
    """Dense retrieval wrapped so a Qdrant failure during search doesn't kill
    the request. Returns [] on failure — empty context reaches generate_node
    and the prompt's rule (3) returns the 'no context' line."""
    try:
        if user_id:
            return get_filtered_retriever(k=k, user_id=user_id).invoke(query)
        return get_retriever(k=k).invoke(query)
    except Exception as exc:
        print(
            f"  [qdrant] dense retrieval failed (k={k}, user_id={user_id}): "
            f"{type(exc).__name__}: {exc} — returning [] (degraded)."
        )
        return []


def retrieve_candidates(
    query: str, k_retrieve: int = 10, user_id: str | None = None
) -> list[str]:
    """Wide candidate pool from dense + BM25, WITHOUT reranking. Used by
    multi-query expansion: pool per variant, dedupe/union, rerank once after.
    Scoped to a user's chunks when user_id is set. Never raises on a Qdrant
    outage — just narrows the pool."""
    dense_docs = _dense_safe(query, k=k_retrieve, user_id=user_id)
    if user_id:
        bm25 = get_user_bm25_retriever(user_id, k=k_retrieve)
        bm25_docs = bm25.invoke(query) if bm25 is not None else []
    else:
        bm25 = get_bm25_retriever(k=k_retrieve)
        bm25_docs = bm25.invoke(query) if bm25 is not None else []
    unique = {doc.page_content for doc in list(dense_docs) + list(bm25_docs)}
    return list(unique)


def rerank_texts(query: str, texts: list[str], k_final: int = 5) -> list[str]:
    """Two-stage retrieval, stage 2: score every [query, text] pair with the
    cross-encoder and keep the sharpest k_final. Falls back to "first k_final
    in pool order" when the reranker failed to load — strictly worse, but the
    request still completes."""
    if not texts:
        return []
    encoder = get_reranker()
    if encoder is None:
        return texts[:k_final]
    scores = encoder.predict([(query, t) for t in texts])
    ranked = sorted(zip(scores, texts, strict=True), key=lambda st: st[0], reverse=True)
    return [t for _, t in ranked[:k_final]]
