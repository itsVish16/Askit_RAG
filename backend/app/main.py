import os
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import agent  # noqa: F401  (re-exported for back-compat imports)
from app.api import ask, auth, eval, health, ingest
from app.config import settings, validate_required_config
from app.core.logger import get_logger
from app.db.chat import flush_loop as chat_flush_loop
from app.db.retrievers import get_bm25_retriever, get_reranker
from app.ingest_worker.runner import start_worker_thread, stop_worker_thread

logger = get_logger(__name__)
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
    logger.info("Pre-building BM25 index + warming reranker at startup...")
    try:
        if await get_bm25_retriever(k=settings.K_RETRIEVE) is None:
            logger.warning("[startup] BM25 unavailable (Qdrant empty/unreachable) — dense-only until Qdrant recovers.")
        else:
            logger.info("[startup] BM25 OK.")
    except Exception as exc:
        logger.error(f"[startup] BM25 build failed (non-fatal): {type(exc).__name__}: {exc}")
    try:
        get_reranker()
        logger.info("[startup] Reranker warmed.")
    except Exception as e:
        logger.error(f"[startup] Warmup failed: {e}")

    start_worker_thread()
    _chat_flush = threading.Thread(target=chat_flush_loop, daemon=True)
    _chat_flush.start()
    logger.info("Retrieval stack ready.")

    def run_evals_delayed():
        import time

        from app.evaluation.evals import run_eval_pipeline_if_needed
        logger.info("[startup] Waiting 10s before checking/running automated evals...")
        time.sleep(10)
        try:
            run_eval_pipeline_if_needed()
        except Exception as exc:
            logger.error(f"[evals] Automated eval pipeline failed: {exc}")

    _eval_thread = threading.Thread(target=run_evals_delayed, daemon=True)
    _eval_thread.start()

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
