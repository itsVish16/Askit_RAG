import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # --- LLM (generation + query transforms) ---
    FIREWORKS_API_KEY: str = os.getenv("FIREWORKS_API_KEY")
    FIREWORKS_BASE_URL = os.getenv("FIREWORKS_BASE_URL")
    FIREWORKS_MODEL_NAME = os.getenv("FIREWORKS_MODEL_NAME")
    # Optional vision model for scanned/image PDFs + image uploads. Same
    # Fireworks base URL; leave blank to disable vision extraction (text-only).
    FIREWORKS_VISION_MODEL_NAME = os.getenv("FIREWORKS_VISION_MODEL_NAME", "")

    # --- Opik observability ---
    OPIK_PROJECT_NAME = os.getenv("OPIK_PROJECT_NAME")
    OPIK_API_KEY = os.getenv("OPIK_API_KEY")
    OPIK_WORKSPACE = os.getenv("OPIK_WORKSPACE")

    # --- Qdrant vector store ---
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    QDRANT_URL = os.getenv("QDRANT_URL")
    # Collection for the Fireworks embedding model. Vector dim is auto-probed
    # from the configured embeddings, so a model swap just needs a new
    # collection name (the old dim-incompatible collection is not reused).
    QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "askit-docs-fireworks")
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
    # Dense embeddings via the Fireworks API (OpenAI-compatible embeddings
    # endpoint, same base URL + key as the LLM). Default is a Fireworks-hosted
    # embedding model; set to any Fireworks embedding id you've enabled.
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "nomic-ai/nomic-embed-text-v1")
    # Cross-encoder reranker (on-device, sentence-transformers). VERIFIED BEST:
    # bge-reranker-v2-m3 (568M) scored WORSE on answer_relevance (0.823 vs
    # 0.859) at 25x the size. Uses the HF cache (HF_HOME).
    RERANKER_MODEL_NAME = os.getenv(
        "RERANKER_MODEL_NAME", "cross-encoder/ms-marco-MiniLM-L6-v2"
    )

    # --- Vision extraction (scanned PDFs / image uploads) ---
    # A page with fewer than this many extracted chars is treated as scanned
    # and routed through the vision model if one is configured.
    VISION_MIN_CHARS = int(os.getenv("VISION_MIN_CHARS", "50"))
    VISION_RENDER_DPI = int(os.getenv("VISION_RENDER_DPI", "200"))

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

    # --- API safety limits (Bug #2 / Task 5.2) ---
    # Hard ceiling on the user's /ask query length. Anything bigger would
    # blow up the multi-query prompt, the Fireworks request, and the memory;
    # 4k chars is roomy for a biomedical question and a tight anti-abuse cap.
    MAX_QUERY_LEN = int(os.getenv("MAX_QUERY_LEN", "4096"))
    # Per-session request rate, enforced in-process by a token bucket. The
    # limiter prevents one client from draining Fireworks quota / Qdrant
    # connections; single uvicorn worker so an in-process dict is enough.
    MAX_RPM_PER_SESSION = int(os.getenv("MAX_RPM_PER_SESSION", "30"))
    # PDF upload ceilings — defence against a giant upload OOM-ing the
    # event loop (the whole file is read into RAM before spooling to disk).
    MAX_PDF_SIZE_MB = int(os.getenv("MAX_PDF_SIZE_MB", "25"))
    MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "10"))
    # --- Latency optimization (smart routing + parallelism) ---
    # Master switch for the router node. When disabled, the graph falls back
    # to the original single-path pipeline (no caching, no complexity routing).
    ROUTE_ENABLED = os.getenv("ROUTE_ENABLED", "true").lower() == "true"
    # Chat-history similarity threshold (0.0–1.0). If the current question's
    # fuzzy match score against a prior HumanMessage exceeds this, the router
    # returns the cached answer and skips all retrieval + generation.
    SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.85"))
    # Override model for the router classifier (cheaper/faster model). Leave
    # empty to reuse the main FIREWORKS_MODEL_NAME.
    ROUTE_CLASSIFIER_MODEL = os.getenv("ROUTE_CLASSIFIER_MODEL", "")

    # Per-user upload cap: a user may keep at most this many completed PDFs.
    MAX_PDFS_PER_USER = int(os.getenv("MAX_PDFS_PER_USER", "5"))
    # PII redaction in persisted chat_history (the InMemorySaver checkpointer
    # stores HumanMessage/AIMessage content verbatim, which is exactly the
    # surface where biomedical PHI would otherwise sit in process RAM). The
    # default is ON; turn off via REDACT_PII=false for local debugging.
    REDACT_PII = os.getenv("REDACT_PII", "true").lower() == "true"

    # --- Auth (name + email + password; bcrypt + JWT) ---
    # sqlite users store (single-process, same pattern as the ingest-status db).
    AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", "data/users.sqlite")
    JWT_SECRET = os.getenv("JWT_SECRET")
    JWT_ALG = os.getenv("JWT_ALG", "HS256")
    JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

    # --- Eval results cache ---
    EVAL_DB_PATH = os.getenv("EVAL_DB_PATH", "data/eval.sqlite")

    # --- CORS (frontend origin) ---
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000")

    # --- S3 (presigned URLs for direct upload) ---
    # Bucket where uploaded files are stored before the worker processes them.
    # When set, files are uploaded directly to S3 by the frontend (presigned
    # URL) and the worker downloads from S3. Leave blank for local-disk upload.
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
    # Optional endpoint for Localstack-style dev/test.
    S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
    # Presigned URL expiry (seconds — 1 hour default).
    S3_PRESIGN_EXPIRY = int(os.getenv("S3_PRESIGN_EXPIRY", "3600"))

    # --- Phase 4: async ingestion pipeline (SQS + in-process worker) ---
    # (so no S3), job status is in a tiny sqlite file (so no DynamoDB), and
    # the worker is a daemon thread inside the FastAPI process (so no Lambda
    # / no ECS / no separate worker binary).
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    # Optional — boto3 will fall back to ~/.aws/credentials if these are
    # blank, so dev on a laptop with `aws configure` doesn't need .env lines.
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    # SQS queue URL. Required when INGEST_WORKER_ENABLED=true.
    SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
    # Visibility timeout must exceed the worst-case processing time for one
    # PDF (chunk + 1024-dim embed + Qdrant upsert). 10 min covers a 200-page
    # 1k-chunk PDF on a laptop CPU with retries.
    SQS_VISIBILITY_TIMEOUT_SEC = int(os.getenv("SQS_VISIBILITY_TIMEOUT_SEC", "600"))
    # Long-poll wait — 20s is the SQS max and minimises empty-receive cost
    # (which is what keeps us inside free tier at high idle).
    SQS_WAIT_SECONDS = int(os.getenv("SQS_WAIT_SECONDS", "20"))
    # Concurrency cap — deliberately 1: ingestion must not starve /ask of
    # CPU in this single-process design. Scale horizontally later.
    SQS_MAX_MESSAGES = int(os.getenv("SQS_MAX_MESSAGES", "1"))
    # After this many receives SQS's RedrivePolicy would move the msg to the
    # DLQ — used by us as a hint to GIVE UP on transient loops and mark the
    # job FAILED locally too.
    SQS_MAX_ATTEMPTS = int(os.getenv("SQS_MAX_ATTEMPTS", "5"))
    # Optional endpoint for Localstack-style dev/test. Boto3 will send all
    # SQS calls here when set. Empty = real AWS.
    SQS_ENDPOINT_URL = os.getenv("SQS_ENDPOINT_URL", "")
    # Local-disk layout: uploaded files land in INGEST_UPLOAD_DIR; job status
    # in a single sqlite file. Both persist across API restarts.
    INGEST_UPLOAD_DIR = os.getenv("INGEST_UPLOAD_DIR", "data/uploads")
    INGEST_STATUS_DB_PATH = os.getenv("INGEST_STATUS_DB_PATH", "data/ingest_jobs.sqlite")
    # File types the /ingest/pdf endpoint accepts (loader registry dispatches
    # by extension). PDF = text + vision fallback; TXT/MD = TextLoader;
    # PNG/JPG/JPEG = vision model direct.
    INGEST_SUPPORTED_EXTENSIONS = os.getenv(
        "INGEST_SUPPORTED_EXTENSIONS", "pdf,txt,md,png,jpg,jpeg"
    )
    # By user's choice: keep PDFs on disk after the worker successfully
    # upserts the chunks (for source-citation follow-up). Set to false to
    # free the disk instead.
    INGEST_KEEP_PDF_AFTER_SUCCESS = os.getenv(
        "INGEST_KEEP_PDF_AFTER_SUCCESS", "true"
    ).lower() == "true"
    # Master switch — set false to keep the API up but skip the worker
        # thread (e.g. on a deploy box that should only answer /ask).
    INGEST_WORKER_ENABLED = os.getenv("INGEST_WORKER_ENABLED", "true").lower() == "true"


settings = Config()


# Fail-fast startup validation. Missing env vars are caught BEFORE serving
# traffic, so a misconfigured deploy can never answer a request with a
# confusing KeyError halfway through. We declare *required* env here; all
# *optional* env already has sensible defaults in the Config class above.
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
    """Return a list of missing required env vars. Empty list = OK.

    A separate function (rather than raising on import) lets the FastAPI
    startup hook produce a clean log line per missing var AND lets `/ready`
    report the same problem live for a running-but-misconfigured app.
    """
    missing: list[str] = []
    for name in REQUIRED_ENV:
        value = os.getenv(name) or getattr(settings, name, None)
        if not value:
            missing.append(name)
    return missing
