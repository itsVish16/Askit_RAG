from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import validate_required_config

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness check with zero downstream I/O."""
    return {"status": "alive", "service": "askit-rag"}


@router.get("/ready")
async def ready():
    """Readiness check for Qdrant, reranker, BM25 cache, and required config (no billable API calls)."""
    checks: list[tuple[str, str, str]] = []
    overall_ok = True

    try:
        from app.db.qdrant import async_qdrant_client

        collections = await async_qdrant_client.get_collections()
        cols = [c.name for c in collections.collections]
        checks.append(("qdrant", "ok", f"collections={cols}"))
    except Exception as exc:
        overall_ok = False
        checks.append(("qdrant", "down", f"{type(exc).__name__}: {exc}"))

    try:
        from app.db.retrievers import get_reranker

        if get_reranker() is None:
            checks.append(("reranker", "degraded", "uninitialized — fallback order used"))
        else:
            checks.append(("reranker", "ok", "loaded"))
    except Exception as exc:
        checks.append(("reranker", "down", f"{type(exc).__name__}: {exc}"))

    try:
        from app.db.retrievers import _bm25_cache_global, _user_bm25_cache

        if _bm25_cache_global is not None or any(v is not None for v in _user_bm25_cache.values()):
            checks.append(("bm25", "ok", "cached"))
        else:
            checks.append(("bm25", "pending", "not yet built"))
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
