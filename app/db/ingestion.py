# app/ingestion.py
import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.db.qdrant import get_vectorstore


def load_parquet_documents(file_path: str) -> list[Document]:
    df = pd.read_parquet(file_path)

    docs: list[Document] = []
    for _, row in df.iterrows():
        for passage in row["documents"]:
            docs.append(Document(page_content=passage))

    print(f"Loaded {len(docs)} raw passages form {file_path}")
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


def embed_and_upsert(chunks: list[Document], batch_size: int = 16) -> None:
    """Embed chunks and upsert to Qdrant in small batches.

    Small batches (16) because each chunk carries a 4096-dim vector —
    big batches exceed Qdrant Cloud's write timeout. If a batch still
    times out, we recursively split it in half until it goes through,
    so one slow request never kills the whole run.
    """
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
    raw = load_parquet_documents("data/ragbench/covidqa/train-00000-of-00001.parquet")
    chunks = chunk_documents(raw)
    embed_and_upsert(chunks)
    print("Collection is ready for retrieval.")
