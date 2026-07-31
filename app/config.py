import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # --- LLM (generation + query transforms) ---
    FIREWORKS_API_KEY: str = os.getenv("FIREWORKS_API_KEY")
    FIREWORKS_BASE_URL = os.getenv("FIREWORKS_BASE_URL")
    FIREWORKS_MODEL_NAME = os.getenv("FIREWORKS_MODEL_NAME")

    # --- Opik observability ---
    OPIK_PROJECT_NAME = os.getenv("OPIK_PROJECT_NAME")
    OPIK_API_KEY = os.getenv("OPIK_API_KEY")
    OPIK_WORKSPACE = os.getenv("OPIK_WORKSPACE")

    # --- Qdrant vector store ---
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    QDRANT_URL = os.getenv("QDRANT_URL")
    # New collection for BGE-large (1024-dim) — its vector size differs from
    # the old Fireworks embeddings (4096-dim), so it can't reuse "Askit-docs".
    QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "askit-docs-bgem3")
    # Raised from the ~5s default: vector batches are large uploads and
    # Qdrant Cloud needs more time to accept them.
    QDRANT_TIMEOUT = int(os.getenv("QDRANT_TIMEOUT", "60"))

    # --- Ingestion / chunking ---
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "850"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
    # Small batches: each chunk carries a 1024-dim vector and big batches
    # exceed Qdrant Cloud's write timeout. Recursive halving handles strays.
    INGEST_BATCH_SIZE = int(os.getenv("INGEST_BATCH_SIZE", "16"))

    # --- Models ---
    # Local dense embeddings via fastembed — replaced Fireworks embeddings
    # whose dense-only recall was 0.096 (BM25 beat them 3.4x).
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-large-en-v1.5")
    # Cross-encoder reranker. VERIFIED BEST: bge-reranker-v2-m3 (568M) scored
    # WORSE on answer_relevance (0.823 vs 0.859) at 25x the size.
    RERANKER_MODEL_NAME = os.getenv(
        "RERANKER_MODEL_NAME", "cross-encoder/ms-marco-MiniLM-L6-v2"
    )

    # --- Retrieval stack knobs (validated via Opik experiments) ---
    # Query expansion: original + N LLM-generated variants.
    MULTI_QUERY_N = int(os.getenv("MULTI_QUERY_N", "4"))
    # Wide net: candidates pulled per query for both dense and BM25.
    K_RETRIEVE = int(os.getenv("K_RETRIEVE", "10"))
    # Sharp net: chunks kept after cross-encoder reranking.
    K_FINAL = int(os.getenv("K_FINAL", "5"))

    # --- Evaluation ---
    EVAL_SAMPLE_SIZE = int(os.getenv("EVAL_SAMPLE_SIZE", "50"))
    EVAL_DATASET_NAME = os.getenv("EVAL_DATASET_NAME", "COVID-QA-full-stack")
    EVAL_PARQUET_PATH = os.getenv(
        "EVAL_PARQUET_PATH", "data/ragbench/covidqa/test-00000-of-00001.parquet"
    )
    INGEST_PARQUET_PATH = os.getenv(
        "INGEST_PARQUET_PATH", "data/ragbench/covidqa/train-00000-of-00001.parquet"
    )


settings = Config()
