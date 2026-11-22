import os
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import agent  # noqa: F401
from app.api import ask, auth, eval, health, ingest
from app.config import settings, validate_required_config
from app.core.logger import get_logger
from app.db.chat import flush as chat_flush
from app.db.chat import flush_loop as chat_flush_loop
from app.db.retrievers import get_bm25_retriever, get_reranker
from app.ingest_worker.runner import start_worker_thread, stop_worker_thread

logger = get_logger(__name__)
if settings.OPIK_PROJECT_NAME:
    os.environ["OPIK_PROJECT_NAME"] = settings.OPIK_PROJECT_NAME


@asynccontextmanager
async def lifespan(_: FastAPI):
    missing = validate_required_config()
    if missing:
        raise RuntimeError(
            "Askit RAG cannot start — required env vars missing: "
            + ", ".join(missing)
            + ". See .env.example."
        )

    logger.info("Warming retrieval stack at startup...")
    try:
        if await get_bm25_retriever(k=settings.K_RETRIEVE) is None:
            logger.warning("[startup] BM25 unavailable — dense-only until Qdrant has documents.")
        else:
            logger.info("[startup] BM25 ready.")
    except Exception as exc:
        logger.error(f"[startup] BM25 build failed (non-fatal): {type(exc).__name__}: {exc}")

    try:
        get_reranker()
        logger.info("[startup] Reranker ready.")
    except Exception as exc:
        logger.error(f"[startup] Reranker warmup failed: {exc}")

    start_worker_thread()
    threading.Thread(target=chat_flush_loop, name="chat-flush", daemon=True).start()

    def run_evals_delayed():
        from app.evaluation.evals import run_eval_pipeline_if_needed

        time.sleep(10)
        try:
            run_eval_pipeline_if_needed()
        except Exception as exc:
            logger.error(f"[evals] Automated eval pipeline failed: {exc}")

    threading.Thread(target=run_evals_delayed, name="eval-runner", daemon=True).start()

    yield

    stop_worker_thread()
    try:
        chat_flush()
    except Exception as exc:
        logger.error(f"[shutdown] chat flush failed: {exc}")


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
