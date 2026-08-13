from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import validate_required_config

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness — must never touch downstream deps (else a Qdrant blip kills
    the pod and triggers a restart storm)."""
    return {"status": "alive", "service": "askit-rag"}


@router.get("/ready")
async def ready():
    """Readiness — probe each dep the way /ask uses it, aggregate into one
    verdict. Returns 503 with failing components. Does NOT call Fireworks
    (would cost money + add latency on every probe); startup env check covers it."""
    checks: list[tuple[str, str, str]] = []
    overall_ok = True

    try:
        from app.db.qdrant import qdrant_client
        cols = [c.name for c in qdrant_client.get_collections().collections]
        checks.append(("qdrant", "ok", f"collections={cols}"))
    except Exception as exc:
        overall_ok = False
        checks.append(("qdrant", "down", f"{type(exc).__name__}: {exc}"))

    try:
        from app.core.llm import embeddings
        vec = embeddings.embed_query("ready probe")
        checks.append(("embeddings", "ok", f"dim={len(vec)}"))
    except Exception as exc:
        overall_ok = False
        checks.append(("embeddings", "down", f"{type(exc).__name__}: {exc}"))

    try:
        from app.db.retrievers import get_reranker
        if get_reranker() is None:
            checks.append(("reranker", "degraded", "load failed — dense pool order used"))
        else:
            checks.append(("reranker", "ok", "loaded"))
    except Exception as exc:
        checks.append(("reranker", "down", f"{type(exc).__name__}: {exc}"))

    try:
        from app.db.retrievers import _bm25_cache_global, _user_bm25_cache
        if _bm25_cache_global is not None or any(v is not None for v in _user_bm25_cache.values()):
            checks.append(("bm25", "ok", "cached"))
        else:
            checks.append(("bm25", "pending", "not yet built; first request triggers build"))
    except Exception as exc:
        checks.append(("bm25", "down", f"{type(exc).__name__}: {exc}"))

    missing = validate_required_config()
    if missing:
        overall_ok = False
        checks.append(("config", "fail", f"missing={missing}"))
    else:
        checks.append(("config", "ok", "all required env present"))

    return JSONResponse(
        status_code=200 if overall_ok else 503,
        content={"ready": overall_ok, "checks": checks},
    )
