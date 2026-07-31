from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from app.config import settings
from app.db.qdrant import get_retriever, qdrant_client

# Load once at import: fast English cross-encoder reranker (~22M params, local CPU).
# VERIFIED BEST: bge-reranker-v2-m3 (568M) was tested and scored WORSE on
# answer_relevance (0.823 vs 0.859) at 25x the size. MiniLM wins on this corpus.
reranker = CrossEncoder(settings.RERANKER_MODEL_NAME)

# BM25 retriever cache: build the keyword index ONCE instead of per-query.
# Rebuilding scrolls all ~5k docs from Qdrant on every question — the
# production-killing latency bug we measured. This caches it process-wide.
_bm25_cache: dict[int, BM25Retriever] = {}


def _fetch_all_documents(batch_size: int = 256) -> list[Document]:
    documents: list[Document] = []
    offset = None

    while True:
        points, offset = qdrant_client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=batch_size,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )

        for point in points:
            documents.append(
                Document(
                    page_content=point.payload["page_content"],
                    metadata=point.payload.get("metadata", {}),
                )
            )

        if offset is None:
            break
    print(f"Fetched {len(documents)} documents from Qdrant for the BM25 index.")
    return documents


def get_bm25_retriever(k: int = 3) -> BM25Retriever:
    """Return a cached BM25 retriever. Index is built once per k, then reused."""
    if k in _bm25_cache:
        return _bm25_cache[k]

    documents = _fetch_all_documents()
    if not documents:
        raise RuntimeError(
            f"Qdrant collection '{settings.QDRANT_COLLECTION}' is empty — "
            "run `uv run python -m app.db.ingestion` before starting the API."
        )
    retriever = BM25Retriever.from_documents(documents)
    retriever.k = k
    _bm25_cache[k] = retriever
    return retriever


def bm25_candidates_from_keywords(keywords: list[str], k: int = 10) -> list[str]:
    """BM25 search using extracted domain keywords instead of the raw question.

    BM25 matches tokens — giving it the entities/synonyms ('SARS-CoV-2',
    'respiratory droplets') instead of vague natural language makes it surgical.
    We query with the joined keyword string AND each keyword individually, to
    catch both multi-term and single-rare-term matches (genes, abbreviations).
    """
    if not keywords:
        return []

    bm25 = get_bm25_retriever(k=k)
    candidates: list[str] = []

    queries_to_try = [" ".join(keywords), *keywords]
    for q in queries_to_try:
        docs = bm25.invoke(q)
        candidates.extend(doc.page_content for doc in docs)

    return list(dict.fromkeys(candidates))  # dedupe, preserve order


def retrieve_candidates(query: str, k_retrieve: int = 10) -> list[str]:
    """Retrieve a wide candidate pool from dense + BM25, WITHOUT reranking.

    Used by multi-query expansion: collect raw candidates per variant,
    dedupe/union them, then rerank the whole pool in ONE pass afterward.
    """
    dense_docs = get_retriever(k=k_retrieve).invoke(query)
    bm25_docs = get_bm25_retriever(k=k_retrieve).invoke(query)

    unique = {doc.page_content for doc in list(dense_docs) + list(bm25_docs)}
    return list(unique)


def rerank_texts(query: str, texts: list[str], k_final: int = 5) -> list[str]:
    """Two-stage retrieval, stage 2: score every [query, text] pair with the
    cross-encoder (which reads the pair jointly, unlike bi-encoder retrieval)
    and keep only the sharpest k_final chunks — a few highly-relevant chunks
    produce more grounded answers than many mixed-relevance ones.
    """
    if not texts:
        return []
    scores = reranker.predict([(query, t) for t in texts])
    ranked = sorted(zip(scores, texts, strict=True), key=lambda st: st[0], reverse=True)
    return [t for _, t in ranked[:k_final]]
