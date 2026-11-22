import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # LLM & Vision (Fireworks OpenAI-compatible API)
    FIREWORKS_API_KEY: str = os.getenv("FIREWORKS_API_KEY", "")
    FIREWORKS_BASE_URL: str | None = os.getenv("FIREWORKS_BASE_URL")
    FIREWORKS_MODEL_NAME: str | None = os.getenv("FIREWORKS_MODEL_NAME")
    FIREWORKS_VISION_MODEL_NAME: str = os.getenv("FIREWORKS_VISION_MODEL_NAME", "")

    # Opik observability
    OPIK_PROJECT_NAME: str | None = os.getenv("OPIK_PROJECT_NAME")
    OPIK_API_KEY: str | None = os.getenv("OPIK_API_KEY")
    OPIK_WORKSPACE: str | None = os.getenv("OPIK_WORKSPACE")

    # Qdrant vector store
    QDRANT_API_KEY: str | None = os.getenv("QDRANT_API_KEY")
    QDRANT_URL: str | None = os.getenv("QDRANT_URL")
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "askit-docs-fireworks")
    QDRANT_TIMEOUT: int = int(os.getenv("QDRANT_TIMEOUT", "60"))

    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "850"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "100"))
    INGEST_BATCH_SIZE: int = int(os.getenv("INGEST_BATCH_SIZE", "16"))

    # Embeddings & Reranker
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "nomic-ai/nomic-embed-text-v1")
    FIREWORKS_RERANK_API_KEY: str = (
        os.getenv("FIREWORKS_API_KEY_0")
        or os.getenv("FIREWORKS_API_KEY_O")
        or os.getenv("FIREWORKS_RERANK_API_KEY")
        or os.getenv("FIREWORKS_API_KEY", "")
    )
    FIREWORKS_RERANK_URL: str = os.getenv(
        "FIREWORKS_RERANK_URL", "https://api.fireworks.ai/inference/v1/rerank"
    )
    RERANKER_MODEL_NAME: str = os.getenv(
        "RERANKER_MODEL_NAME", "accounts/fireworks/models/qwen3-reranker-8b"
    )

    # Vision OCR thresholds
    VISION_MIN_CHARS: int = int(os.getenv("VISION_MIN_CHARS", "50"))
    VISION_RENDER_DPI: int = int(os.getenv("VISION_RENDER_DPI", "200"))

    # Retrieval parameters
    MULTI_QUERY_N: int = int(os.getenv("MULTI_QUERY_N", "4"))
    K_RETRIEVE: int = int(os.getenv("K_RETRIEVE", "10"))
    K_FINAL: int = int(os.getenv("K_FINAL", "5"))

    # Evaluation
    EVAL_SAMPLE_SIZE: int = int(os.getenv("EVAL_SAMPLE_SIZE", "50"))
    EVAL_DATASET_NAME: str = os.getenv("EVAL_DATASET_NAME", "COVID-QA-full-stack")
    EVAL_JUDGE_MODEL: str = os.getenv("EVAL_JUDGE_MODEL", "")
    EVAL_PARQUET_PATH: str = os.getenv(
        "EVAL_PARQUET_PATH", "data/ragbench/covidqa/test-00000-of-00001.parquet"
    )
    INGEST_PARQUET_PATH: str = os.getenv(
        "INGEST_PARQUET_PATH", "data/ragbench/covidqa/train-00000-of-00001.parquet"
    )

    # Safety & rate limits
    MAX_QUERY_LEN: int = int(os.getenv("MAX_QUERY_LEN", "4096"))
    MAX_RPM_PER_SESSION: int = int(os.getenv("MAX_RPM_PER_SESSION", "30"))
    MAX_PDF_SIZE_MB: int = int(os.getenv("MAX_PDF_SIZE_MB", "25"))
    MAX_PDF_PAGES: int = int(os.getenv("MAX_PDF_PAGES", "10"))
    MAX_PDFS_PER_USER: int = int(os.getenv("MAX_PDFS_PER_USER", "5"))
    REDACT_PII: bool = os.getenv("REDACT_PII", "true").lower() == "true"

    # Routing
    ROUTE_ENABLED: bool = os.getenv("ROUTE_ENABLED", "true").lower() == "true"
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.85"))
    ROUTE_CLASSIFIER_MODEL: str = os.getenv("ROUTE_CLASSIFIER_MODEL", "")

    # Auth & SQLite paths
    AUTH_DB_PATH: str = os.getenv("AUTH_DB_PATH", "data/users.sqlite")
    EVAL_DB_PATH: str = os.getenv("EVAL_DB_PATH", "data/eval.sqlite")
    JWT_SECRET: str | None = os.getenv("JWT_SECRET")
    JWT_ALG: str = os.getenv("JWT_ALG", "HS256")
    JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")

    # S3 uploads
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "")
    S3_ENDPOINT_URL: str = os.getenv("S3_ENDPOINT_URL", "")
    S3_PRESIGN_EXPIRY: int = int(os.getenv("S3_PRESIGN_EXPIRY", "3600"))

    # SQS & local ingestion worker
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
    SQS_QUEUE_URL: str = os.getenv("SQS_QUEUE_URL", "")
    SQS_VISIBILITY_TIMEOUT_SEC: int = int(os.getenv("SQS_VISIBILITY_TIMEOUT_SEC", "600"))
    SQS_WAIT_SECONDS: int = int(os.getenv("SQS_WAIT_SECONDS", "20"))
    SQS_MAX_MESSAGES: int = int(os.getenv("SQS_MAX_MESSAGES", "1"))
    SQS_MAX_ATTEMPTS: int = int(os.getenv("SQS_MAX_ATTEMPTS", "5"))
    SQS_ENDPOINT_URL: str = os.getenv("SQS_ENDPOINT_URL", "")
    INGEST_UPLOAD_DIR: str = os.getenv("INGEST_UPLOAD_DIR", "data/uploads")
    INGEST_STATUS_DB_PATH: str = os.getenv("INGEST_STATUS_DB_PATH", "data/ingest_jobs.sqlite")
    INGEST_SUPPORTED_EXTENSIONS: str = os.getenv(
        "INGEST_SUPPORTED_EXTENSIONS", "pdf,txt,md,png,jpg,jpeg"
    )
    INGEST_KEEP_PDF_AFTER_SUCCESS: bool = (
        os.getenv("INGEST_KEEP_PDF_AFTER_SUCCESS", "true").lower() == "true"
    )
    INGEST_WORKER_ENABLED: bool = os.getenv("INGEST_WORKER_ENABLED", "true").lower() == "true"


settings = Config()

REQUIRED_ENV: tuple[str, ...] = (
    "FIREWORKS_API_KEY",
    "FIREWORKS_BASE_URL",
    "FIREWORKS_MODEL_NAME",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "OPIK_API_KEY",
    "OPIK_WORKSPACE",
    "OPIK_PROJECT_NAME",
    "JWT_SECRET",
)


def validate_required_config() -> list[str]:
    """Return missing required environment variable names."""
    return [
        name
        for name in REQUIRED_ENV
        if not (os.getenv(name) or getattr(settings, name, None))
    ]
