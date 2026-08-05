import uuid

import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.core.logger import get_logger
from app.db.loaders import load_document
from app.db.qdrant import get_vectorstore

logger = get_logger(__name__)


def load_parquet_documents(file_path: str | None = None) -> list[Document]:
    """Load the RAGBench COVID-QA train split for one-shot corpus seeding."""
    path = file_path or settings.INGEST_PARQUET_PATH
    df = pd.read_parquet(path)
    docs = [Document(page_content=passage) for _, row in df.iterrows() for passage in row["documents"]]
    logger.info(f"Loaded {len(docs)} raw passages from {path}")
    return docs


def load_pdf_documents(file_path: str, user_id: str) -> list[Document]:
    return load_document(file_path, user_id)

def chunk_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_overlap=settings.CHUNK_OVERLAP,
        chunk_size=settings.CHUNK_SIZE,
        length_function=len,
        is_separator_regex=False,
    )
    chunks = splitter.split_documents(docs)
    logger.info(f"Split into {len(chunks)} chunks")
    return chunks

def embed_and_upsert(
    chunks: list[Document],
    batch_size: int | None = None,
    ids: list[str] | None = None,
) -> None:
    if ids is not None and len(ids) != len(chunks):
        raise ValueError(
            f"ids length {len(ids)} != chunks length {len(chunks)}; "
            "ids must align 1:1 with chunks for idempotent upserts."
        )
    batch_size = batch_size or settings.INGEST_BATCH_SIZE
    vectorstore = get_vectorstore()
    total = len(chunks)

    def upsert(batch: list[Document], batch_ids: list[str] | None) -> None:
        try:
            if batch_ids is None:
                vectorstore.add_documents(batch)
            else:
                vectorstore.add_documents(batch, ids=batch_ids)
        except Exception:
            if len(batch) == 1:
                raise  # a single chunk failing is a real error, not a size issue
            mid = len(batch) // 2
            upsert(batch[:mid], batch_ids[:mid] if batch_ids is not None else None)
            upsert(batch[mid:], batch_ids[mid:] if batch_ids is not None else None)

    for start in range(0, total, batch_size):
        end = start + batch_size
        batch_ids = ids[start:end] if ids is not None else None
        upsert(chunks[start:end], batch_ids)
        logger.info(f"Upserted {min(end, total)}/{total} chunks")
        
    # Invalidate the BM25 disk cache so the new chunks are included on next retrieval
    if chunks:
        user_id = chunks[0].metadata.get("user_id")
        from app.db.retrievers import invalidate_user_bm25_cache
        if user_id:
            invalidate_user_bm25_cache(user_id)
        else:
            # If no user_id, it might be the global corpus ingest
            invalidate_user_bm25_cache("global")


# removed ingest_pdf

if __name__ == "__main__":
    raw = load_parquet_documents()
    chunks = chunk_documents(raw)
    embed_and_upsert(chunks)
    logger.info("Collection is ready for retrieval.")
