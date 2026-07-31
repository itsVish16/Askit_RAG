from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import settings
from app.core.llm import embeddings

# Shared client, reused across all retrievers.
qdrant_client = QdrantClient(
    api_key=settings.QDRANT_API_KEY,
    url=settings.QDRANT_URL,
    timeout=settings.QDRANT_TIMEOUT,
)


def _ensure_collection() -> None:
    """Create the collection if it doesn't exist yet.

    Vector size must be declared up front. We get it by embedding one
    probe string and measuring the result — so the size always matches
    whatever embedding model is configured, with no hardcoded dimension.
    COSINE distance is the standard for semantic text similarity.
    """
    existing = {c.name for c in qdrant_client.get_collections().collections}
    if settings.QDRANT_COLLECTION not in existing:
        vector_size = len(embeddings.embed_query("probe"))
        qdrant_client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        print(f"Created collection '{settings.QDRANT_COLLECTION}' (size={vector_size})")


def get_vectorstore() -> QdrantVectorStore:
    """Wrap the Qdrant collection as a LangChain VectorStore.

    Creates the collection first if it doesn't exist yet.
    No data is downloaded — search happens server-side on Qdrant.
    """
    _ensure_collection()
    return QdrantVectorStore(
        collection_name=settings.QDRANT_COLLECTION,
        embedding=embeddings,
        client=qdrant_client,
    )


def get_retriever(k: int = 3):
    return get_vectorstore().as_retriever(search_kwargs={"k": k})


if __name__ == "__main__":
    collections = qdrant_client.get_collections()
    print("Connected. Collections:", [c.name for c in collections.collections])
