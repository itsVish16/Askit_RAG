from qdrant_client import AsyncQdrantClient
from app.config import settings
import asyncio
from app.core.llm import embeddings


COLLECTION_NMAE = "Askit-docs"

qdrant_client = AsyncQdrantClient(
    api_key=settings.QDRANT_API_KEY,
    url=settings.QDRANT_URL
)

async def get_qdrant() -> AsyncQdrantClient:
   return  qdrant_client

async def main():
    # Test the connection using an async method
    collections = await qdrant_client.get_collections()
    print("vector db connected")

async def get_retriever(k: int = 3):
    """
    Connects to a pre-existing Qdrant Cloud Collection and
    return a langchain retriever
    """

    vectorstore = QdrantVectorStore.from_existing_collection(
        collection_name = COLLECTION_NMAE,
        embedding = embeddings,
        url = settings.QDRANT_URL,
        api_key = settings.QDRANT_API_KEY
    )
    
    return vectorstore.as_retriever(search_kwargs={"k": k})

if __name__ ==  "__main__":
   asyncio.run(main())