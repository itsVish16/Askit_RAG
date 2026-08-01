from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    VectorParams,
)

from app.config import settings
from app.core.llm import embeddings

qdrant_client = QdrantClient(
    api_key=settings.QDRANT_API_KEY,
    url=settings.QDRANT_URL,
    timeout=settings.QDRANT_TIMEOUT,
)

# Caches that the metadata.user_id keyword payload index exists, so we don't
# issue create_payload_index on every request.
_user_id_index_ensured: bool = False


def _ensure_collection() -> None:
    """Create the collection if absent. Vector size is probed from the
    configured embedding model (no hardcoded dim). COSINE for semantic text."""
    existing = {c.name for c in qdrant_client.get_collections().collections}
    if settings.QDRANT_COLLECTION not in existing:
        vector_size = len(embeddings.embed_query("probe"))
        qdrant_client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        print(f"Created collection '{settings.QDRANT_COLLECTION}' (size={vector_size})")
    _ensure_user_id_index()


def _ensure_user_id_index() -> None:
    """Create a keyword payload index on metadata.user_id if absent. Qdrant
    refuses filtered scroll/search on an unindexed field; per-user PDF scoping
    depends on this filter, so we create it eagerly and cache the success."""
    global _user_id_index_ensured
    if _user_id_index_ensured:
        return
    try:
        qdrant_client.create_payload_index(
            collection_name=settings.QDRANT_COLLECTION,
            field_name="metadata.user_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        print("Ensured payload index on metadata.user_id (keyword).")
    except Exception as exc:
        # 409 = already exists, fine; anything else just log so a transient
        # startup issue doesn't crash the app.
        if "already exists" not in str(exc) and "409" not in str(exc):
            print(f"Skipping user_id index creation: {exc}")
    _user_id_index_ensured = True


def get_vectorstore() -> QdrantVectorStore:
    """Wrap the Qdrant collection as a LangChain VectorStore (creates the
    collection first if needed). Search runs server-side on Qdrant."""
    _ensure_collection()
    return QdrantVectorStore(
        collection_name=settings.QDRANT_COLLECTION,
        embedding=embeddings,
        client=qdrant_client,
    )


def get_retriever(k: int = 3):
    return get_vectorstore().as_retriever(search_kwargs={"k": k})


def user_scope_filter(user_id: str | None) -> Filter | None:
    """Qdrant payload filter restricting retrieval to one user's documents.
    None when there's no scope (= retrieve over the whole shared corpus).
    Key is metadata.user_id because langchain-qdrant stores Document metadata
    under that payload path."""
    if not user_id:
        return None
    return Filter(must=[FieldCondition(key="metadata.user_id", match=MatchValue(value=user_id))])


def get_filtered_retriever(k: int, user_id: str):
    """Scoped dense retriever — used by /ask when a user_id is supplied so the
    LLM grounds only on chunks that user uploaded, never the shared corpus."""
    return get_vectorstore().as_retriever(
        search_kwargs={"k": k, "filter": user_scope_filter(user_id)}
    )


if __name__ == "__main__":
    collections = qdrant_client.get_collections()
    print("Connected. Collections:", [c.name for c in collections.collections])
