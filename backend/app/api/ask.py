import time
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from opik.integrations.langchain import OpikTracer
from pydantic import BaseModel, Field

from app.agent.graph import agent
from app.api.deps import get_current_user
from app.config import settings
from app.core.security import UserPublic

router = APIRouter()

# In-process token-bucket rate limiter (per session_id, sliding 60s window).
# Single uvicorn worker = single process, so an in-process dict is enough.
# Swap for Redis when running multiple workers (Phase 5).
_session_hits: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(session_id: str) -> None:
    """Raise HTTP 429 if session_id exceeded MAX_RPM_PER_SESSION in the last minute."""
    now = time.time()
    window = 60.0
    hits = _session_hits[session_id]
    cutoff = now - window
    while hits and hits[0] < cutoff:
        hits.pop(0)
    if len(hits) >= settings.MAX_RPM_PER_SESSION:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: {settings.MAX_RPM_PER_SESSION} requests/min "
                f"for session_id={session_id}. Back off and retry."
            ),
        )
    hits.append(now)
    _session_hits[session_id] = hits


class UserInput(BaseModel):
    # Cap length: a bigger query blows the multi-query prompt budget and the
    # persisted chat_history. Strip NUL/control bytes (keep \n for multi-line).
    query: str = Field(..., max_length=settings.MAX_QUERY_LEN)
    session_id: str | None = None  # reuse to group a conversation under one Opik thread
    user_id: str | None = None  # deprecated — retrieval is always scoped to the logged-in user

    @classmethod
    def _normalize(cls, value: str) -> str:
        return "".join(c for c in value if c == "\n" or (c >= " " and c != "\x7f"))

    def __init__(self, **data):
        super().__init__(**data)
        object.__setattr__(self, "query", self._normalize(self.query).strip())


class QueryResponse(BaseModel):
    answer: str
    session_id: str
    queries: list[str]
    keywords: list[str]
    context: list[str]
    num_candidates: int


@router.post("/ask", response_model=QueryResponse)
async def ask_query(user_input: UserInput, current_user: UserPublic = Depends(get_current_user)):
    session_id = user_input.session_id or str(uuid.uuid4())
    _check_rate_limit(session_id)

    # Retrieval is ALWAYS scoped to the logged-in user's uploaded PDFs — the
    # client can't widen the scope. user_id from the JWT overrides any input.
    opik_tracer = OpikTracer(thread_id=session_id)
    result = agent.invoke(
        {"question": user_input.query, "user_id": current_user.id},
        config={"configurable": {"thread_id": session_id}, "callbacks": [opik_tracer]},
    )
    opik_tracer.flush()
    return QueryResponse(
        answer=result["answer"],
        session_id=session_id,
        queries=result["queries"],
        keywords=result["keywords"],
        context=result["context"],
        num_candidates=result["num_candidates"],
    )
