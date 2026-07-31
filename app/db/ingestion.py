# app/ingestion.py
import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.db.qdrant import get_vectorstore


def load_parquet_documents(file_path: str | None = None) -> list[Document]:
    path = file_path or settings.INGEST_PARQUET_PATH
    df = pd.read_parquet(path)

    docs: list[Document] = []
    for _, row in df.iterrows():
        for passage in row["documents"]:
            docs.append(Document(page_content=passage))

    print(f"Loaded {len(docs)} raw passages from {path}")
    return docs


def chunk_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_overlap=settings.CHUNK_OVERLAP,
        chunk_size=settings.CHUNK_SIZE,
        length_function=len,
        is_separator_regex=False,
    )
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks")
    return chunks


def embed_and_upsert(
    chunks: list[Document], batch_size: int | None = None
) -> None:
    """Embed chunks and upsert to Qdrant in small batches.

    Small batches: each chunk carries a 1024-dim vector and big batches
    exceed Qdrant Cloud's write timeout. If a batch still times out, we
    recursively split it in half until it goes through, so one slow
    request never kills the whole run.
    """
    batch_size = batch_size or settings.INGEST_BATCH_SIZE
    vectorstore = get_vectorstore()
    total = len(chunks)

    def upsert(batch: list[Document]) -> None:
        try:
            vectorstore.add_documents(batch)
        except Exception:
            if len(batch) == 1:
                raise  # a single chunk failing is a real error, not a size issue
            mid = len(batch) // 2
            upsert(batch[:mid])
            upsert(batch[mid:])

    for start in range(0, total, batch_size):
        upsert(chunks[start : start + batch_size])
        print(f"Upserted {min(start + batch_size, total)}/{total} chunks")


if __name__ == "__main__":
    raw = load_parquet_documents()
    chunks = chunk_documents(raw)
    embed_and_upsert(chunks)
    print("Collection is ready for retrieval.")
