import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import agent  # noqa: F401  (re-exported for back-compat imports)
from app.api import ask, auth, eval, health, ingest
from app.config import settings, validate_required_config
from app.db.retrievers import get_bm25_retriever, rerank_texts
from app.ingest_worker.runner import start_worker_thread, stop_worker_thread

os.environ["OPIK_PROJECT_NAME"] = settings.OPIK_PROJECT_NAME


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail fast on misconfiguration — a deploy missing FIREWORKS_API_KEY /
    # QDRANT_URL / JWT_SECRET should never start serving.
    missing = validate_required_config()
    if missing:
        raise RuntimeError(
            "Askit RAG cannot start — required env vars missing: "
            + ", ".join(missing)
            + ". See .env.example for the full list."
        )

    # Pre-build BM25 + warm the reranker so the first request doesn't pay
    # index-build / model-load latency. Both fault-tolerant: a Qdrant blip at
    # startup logs and continues so /ready can report it live.
    print("Pre-building BM25 index + warming reranker at startup...")
    try:
        if get_bm25_retriever(k=settings.K_RETRIEVE) is None:
            print("  [startup] BM25 unavailable (Qdrant empty/unreachable) — dense-only until Qdrant recovers.")
        else:
            print("  [startup] BM25 OK.")
    except Exception as exc:
        print(f"  [startup] BM25 build failed (non-fatal): {type(exc).__name__}: {exc}")
    try:
        rerank_texts("warmup", ["warmup document"], k_final=1)
        print("  [startup] Reranker warmed.")
    except Exception as exc:
        print(f"  [startup] Reranker warmup failed (non-fatal): {type(exc).__name__}: {exc}")

    start_worker_thread()
    print("Retrieval stack ready.")
    yield
    stop_worker_thread()


app = FastAPI(title="Askit RAG", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ask.router)
app.include_router(ingest.router)
app.include_router(eval.router)
app.include_router(health.router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
