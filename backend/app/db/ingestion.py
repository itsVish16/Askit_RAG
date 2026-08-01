import uuid

import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.db.loaders import load_document
from app.db.qdrant import get_vectorstore


def load_parquet_documents(file_path: str | None = None) -> list[Document]:
    """Load the RAGBench COVID-QA train split for one-shot corpus seeding."""
    path = file_path or settings.INGEST_PARQUET_PATH
    df = pd.read_parquet(path)
    docs = [Document(page_content=passage) for _, row in df.iterrows() for passage in row["documents"]]
    print(f"Loaded {len(docs)} raw passages from {path}")
    return docs


def load_pdf_documents(file_path: str, user_id: str) -> list[Document]:
    """Load a single uploaded file (PDF/TXT/MD/image) via the loader registry.

    Name kept for back-compat with the ingest worker. Tags every chunk with
    metadata.user_id (the per-user scope key), metadata.source, metadata.filename.
    """
    return load_document(file_path, user_id)


def chunk_documents(docs: list[Document]) -> list[Document]:
    """Split long pages/passages into ~CHUNK_SIZE pieces. Preserves metadata
    (user_id / source / filename travel onto every chunk automatically)."""
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
    chunks: list[Document],
    batch_size: int | None = None,
    ids: list[str] | None = None,
) -> None:
    """Embed chunks and upsert to Qdrant in small batches.

    Small batches: each chunk carries a 1024-dim vector and big batches exceed
    Qdrant Cloud's write timeout. If a batch still times out, recursively halve
    it until it goes through, so one slow request never kills the whole run.

    Idempotent mode (Phase 4): pass `ids` aligned 1:1 with `chunks` to upsert
    by deterministic point_id — an SQS at-least-once redelivery then overwrites
    instead of producing duplicate vectors.
    """
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
        print(f"Upserted {min(end, total)}/{total} chunks")


def ingest_pdf(file_path: str, user_id: str | None = None) -> dict:
    """One-shot: load a file, chunk it, upsert into Qdrant. Returns status.

    Used by the /ingest/pdf endpoint's inline fallback. Generates a fresh
    user_id when none is supplied so an anonymous client still gets isolated scope.
    """
    uid = user_id or str(uuid.uuid4())
    pages = load_pdf_documents(file_path, uid)
    if not pages:
        return {"user_id": uid, "num_chunks": 0, "status": "empty"}
    chunks = chunk_documents(pages)
    embed_and_upsert(chunks)
    return {"user_id": uid, "num_chunks": len(chunks), "status": "ok"}


if __name__ == "__main__":
    raw = load_parquet_documents()
    chunks = chunk_documents(raw)
    embed_and_upsert(chunks)
    print("Collection is ready for retrieval.")
