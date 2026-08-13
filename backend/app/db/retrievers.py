import asyncio
import pickle
import random
from collections import OrderedDict
from pathlib import Path

import httpx
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from app.config import settings
from app.core.logger import get_logger
from app.db.qdrant import (
    async_qdrant_client,
    get_filtered_retriever,
    get_retriever,
    user_scope_filter,
)

logger = get_logger(__name__)


class FireworksReranker:
    """Client for the Fireworks / Cohere-compatible Cloud Reranker API."""

    def __init__(self, api_key: str, url: str, model: str):
        self.api_key = api_key
        self.url = url
        self.model = model

    def rerank(self, query: str, texts: list[str], top_n: int = 5) -> list[str]:
        if not texts:
            return []
        if not self.api_key:
            logger.warning("[reranker] FIREWORKS_RERANK_API_KEY is not set — returning original candidate order.")
            return texts[:top_n]

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "query": query,
            "documents": texts,
            "top_n": top_n,
            "return_documents": False,
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(self.url, headers=headers, json=payload)
                if response.status_code != 200:
                    logger.warning(
                        f"[reranker] Fireworks API returned HTTP {response.status_code}: {response.text} — "
                        "falling back to original order."
                    )
                    return texts[:top_n]

                data = response.json()
                results = data.get("results", [])
                if not results:
                    return texts[:top_n]

                sorted_results = sorted(results, key=lambda x: x.get("relevance_score", 0), reverse=True)
                sorted_indices = [item["index"] for item in sorted_results if "index" in item]
                ranked_docs = [texts[idx] for idx in sorted_indices if idx < len(texts)]

                for t in texts:
                    if t not in ranked_docs and len(ranked_docs) < top_n:
                        ranked_docs.append(t)

                return ranked_docs[:top_n]
        except Exception as exc:
            logger.warning(f"[reranker] HTTP call failed: {type(exc).__name__}: {exc} — fallback to original order.")
            return texts[:top_n]


# Reranker instance singleton
reranker: FireworksReranker | None = None
_reranker_initialized: bool = False


class LRUCache:
    def __init__(self, capacity: int):
        self.cache = OrderedDict()
        self.capacity = capacity

    def get(self, key):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)


rerank_cache = LRUCache(10000)


def get_reranker() -> FireworksReranker | None:
    """Return the cached Fireworks cloud reranker client."""
    global reranker, _reranker_initialized
    if _reranker_initialized:
        return reranker
    _reranker_initialized = True
    reranker = FireworksReranker(
        api_key=settings.FIREWORKS_RERANK_API_KEY,
        url=settings.FIREWORKS_RERANK_URL,
        model=settings.RERANKER_MODEL_NAME,
    )
    logger.info(f"[reranker] initialized Fireworks API reranker ({settings.RERANKER_MODEL_NAME}) OK.")
    return reranker


BM25_CACHE_DIR = Path("data/bm25_cache")

# Memory caches (no longer keyed by k)
_bm25_cache_global: BM25Retriever | None = None
_user_bm25_cache: dict[str, BM25Retriever | None] = {}
_global_bm25_initialized: bool = False


async def _scroll_with_retry(scroll_fn, *, max_attempts: int = 4, base_delay: float = 0.5):
    last_exc = None
    for attempt in range(max_attempts):
        try:
            points, offset = await scroll_fn()
            return True, (points, offset)
        except Exception as exc:
            last_exc = exc
            status = getattr(exc, "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                break
            delay = min(8.0, base_delay * (2 ** attempt)) * random.uniform(0.5, 1.0)
            logger.warning(
                f"[qdrant retry] attempt={attempt + 1}/{max_attempts} "
                f"status={status} err={type(exc).__name__}: {exc} — sleeping {delay:.2f}s"
            )
            await asyncio.sleep(delay)
    return False, last_exc


async def _fetch_all_documents(batch_size: int = 256) -> list[Document]:
    documents: list[Document] = []
    offset = None

    async def call():
        return await async_qdrant_client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=batch_size,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )

    while True:
        ok, result = await _scroll_with_retry(call)
        if not ok:
            logger.error(f"[qdrant] giving up on _fetch_all_documents: {result}")
            return []
        points, offset = result
        for point in points:
            documents.append(
                Document(page_content=point.payload["page_content"], metadata=point.payload.get("metadata", {}))
            )
        if offset is None:
            break
    logger.info(f"Fetched {len(documents)} documents from Qdrant for the BM25 index.")
    return documents


async def _fetch_user_documents(user_id: str, batch_size: int = 256) -> list[Document]:
    documents: list[Document] = []
    offset = None
    flt = user_scope_filter(user_id)

    async def call():
        return await async_qdrant_client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=batch_size,
            with_payload=True,
            with_vectors=False,
            offset=offset,
            scroll_filter=flt,
        )

    while True:
        ok, result = await _scroll_with_retry(call)
        if not ok:
            logger.error(f"[qdrant] giving up on _fetch_user_documents({user_id}): {result}")
            return []
        points, offset = result
        for point in points:
            documents.append(
                Document(page_content=point.payload["page_content"], metadata=point.payload.get("metadata", {}))
            )
        if offset is None:
            break
    logger.info(f"Fetched {len(documents)} documents for user_id={user_id} (BM25 index).")
    return documents


async def _load_or_build_bm25(user_id: str | None = None) -> BM25Retriever | None:
    cache_key = user_id if user_id else "global"
    
    # 1. Memory Check
    global _bm25_cache_global, _global_bm25_initialized
    if user_id:
        if user_id in _user_bm25_cache:
            return _user_bm25_cache[user_id]
    else:
        if _global_bm25_initialized:
            return _bm25_cache_global
            
    # 2. Disk Check
    BM25_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = BM25_CACHE_DIR / f"{cache_key}.pkl"
    
    if cache_file.exists():
        try:
            def load_pickle():
                with open(cache_file, "rb") as f:
                    return pickle.load(f)
            retriever = await asyncio.to_thread(load_pickle)
            logger.info(f"[bm25] loaded {cache_key} index from disk cache.")
            if user_id:
                _user_bm25_cache[user_id] = retriever
            else:
                _bm25_cache_global = retriever
                _global_bm25_initialized = True
            return retriever
        except Exception as exc:
            logger.error(f"[bm25] disk cache load failed for {cache_key}: {exc}")
            
    # 3. Build
    documents = await _fetch_user_documents(user_id) if user_id else await _fetch_all_documents()
    
    if not documents:
        if user_id:
            _user_bm25_cache[user_id] = None
        else:
            _bm25_cache_global = None
            _global_bm25_initialized = True
        return None
        
    retriever = BM25Retriever.from_documents(documents)
    retriever.k = 100 # Allow generous slicing by caller
    
    # 4. Save
    try:
        def save_pickle():
            with open(cache_file, "wb") as f:
                pickle.dump(retriever, f)
        await asyncio.to_thread(save_pickle)
    except Exception as exc:
        logger.error(f"[bm25] disk cache save failed for {cache_key}: {exc}")
        
    if user_id:
        _user_bm25_cache[user_id] = retriever
    else:
        _bm25_cache_global = retriever
        _global_bm25_initialized = True
        
    return retriever


async def get_bm25_retriever(k: int = 3) -> BM25Retriever | None:
    # `k` parameter is kept for backward compatibility in imports, but we ignore it for caching
    return await _load_or_build_bm25(user_id=None)

async def get_user_bm25_retriever(user_id: str, k: int = 3) -> BM25Retriever | None:
    return await _load_or_build_bm25(user_id=user_id)


def invalidate_user_bm25_cache(user_id: str):
    """Called by the ingest worker when new documents are added to a user's index."""
    _user_bm25_cache.pop(user_id, None)
        
    cache_file = BM25_CACHE_DIR / f"{user_id}.pkl"
    if cache_file.exists():
        try:
            cache_file.unlink()
        except OSError:
            pass


async def bm25_candidates_from_keywords(
    keywords: list[str], k: int = 10, user_id: str | None = None
) -> list[str]:
    if not keywords:
        return []
        
    bm25 = await _load_or_build_bm25(user_id=user_id)
    if bm25 is None:
        return []
        
    candidates: list[str] = []
    tasks = [bm25.ainvoke(q) for q in [" ".join(keywords), *keywords]]
    results = await asyncio.gather(*tasks)
    
    for docs in results:
        candidates.extend(doc.page_content for doc in docs[:k])
        
    return list(dict.fromkeys(candidates))


async def _dense_safe(query: str, k: int, user_id: str | None) -> list[Document]:
    try:
        if user_id:
            return await get_filtered_retriever(k=k, user_id=user_id).ainvoke(query)
        return await get_retriever(k=k).ainvoke(query)
    except Exception as exc:
        logger.warning(
            f"[qdrant] dense retrieval failed (k={k}, user_id={user_id}): "
            f"{type(exc).__name__}: {exc} — returning [] (degraded)."
        )
        return []


async def retrieve_candidates(
    query: str, k_retrieve: int = 10, user_id: str | None = None
) -> list[str]:
    dense_task = asyncio.create_task(_dense_safe(query, k=k_retrieve, user_id=user_id))
    bm25_task = asyncio.create_task(_load_or_build_bm25(user_id=user_id))
        
    dense_docs, bm25 = await asyncio.gather(dense_task, bm25_task)
    
    if bm25 is not None:
        bm25_docs = (await bm25.ainvoke(query))[:k_retrieve]
    else:
        bm25_docs = []
        
    unique = {doc.page_content for doc in list(dense_docs) + list(bm25_docs)}
    return list(unique)


def rerank_texts(query: str, texts: list[str], k_final: int = 5) -> list[str]:
    if not texts:
        return []

    # 1. Check LRU Cache
    cache_key = (query, tuple(texts), k_final)
    cached = rerank_cache.get(cache_key)
    if cached is not None:
        return cached

    reranker_client = get_reranker()
    if reranker_client is None:
        return texts[:k_final]

    ranked = reranker_client.rerank(query, texts, top_n=k_final)
    rerank_cache.put(cache_key, ranked)
    return ranked
