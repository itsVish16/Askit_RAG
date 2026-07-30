from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document

from app.config import settings
from app.db.qdrant import get_retriever, qdrant_client


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
    print(f"fetched {len(documents)} documents from Qdrant for BM25")
    return documents


def get_bm25_retriever(k: int = 3) -> BM25Retriever:
    documents = _fetch_all_documents()
    if not documents:
        raise RuntimeError(
            f"Qdrant collection '{settings.QDRANT_COLLECTION}' is empty — "
            "run `uv run python -m app.db.ingestion` before starting the API."
        )
    retriever = BM25Retriever.from_documents(documents)
    retriever.k = k
    return retriever


def get_hybrid_retriever(k: int = 3, dense_weight: float = 0.5) -> EnsembleRetriever:
    dense = get_retriever(k=k)
    keyword = get_bm25_retriever(k=k)

    return EnsembleRetriever(
        retrievers=[dense, keyword],
        weights=[dense_weight, 1.0 - dense_weight],
    )
