"""Ask endpoints (POST /ask, POST /ask/stream) and chat session CRUD."""

import asyncio
import json
import time
import uuid
from collections import defaultdict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from opik.integrations.langchain import OpikTracer
from pydantic import BaseModel, Field

from app.agent.graph import agent
from app.api.deps import get_current_user
from app.config import settings
from app.core.logger import get_logger, set_session_id
from app.core.redact import redact_pii
from app.core.security import UserPublic
from app.db.chat import (
    create_session,
    flush,
    get_messages,
    get_session,
    get_sessions_by_user,
    queue_message,
    touch_session,
    update_session_title,
)
from app.db.chat import delete_session as db_delete_session

router = APIRouter()
logger = get_logger(__name__)

_session_hits: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str) -> None:
    now = time.time()
    cutoff = now - 60.0

    # Prune stale keys periodically to prevent unbounded memory growth.
    if len(_session_hits) > 1024:
        stale = [k for k, v in _session_hits.items() if not v or v[-1] < cutoff]
        for k in stale:
            _session_hits.pop(k, None)

    hits = _session_hits[key]
    while hits and hits[0] < cutoff:
        hits.pop(0)
    if len(hits) >= settings.MAX_RPM_PER_SESSION:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.MAX_RPM_PER_SESSION} requests/min. Back off and retry.",
        )
    hits.append(now)


def _verify_session_ownership(session_id: str, user_id: str) -> None:
    sess = get_session(session_id)
    if sess is not None and sess["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Session not found.")


class UserInput(BaseModel):
    query: str = Field(..., max_length=settings.MAX_QUERY_LEN)
    session_id: str | None = None
    user_id: str | None = None

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
async def ask_query(
    user_input: UserInput,
    background_tasks: BackgroundTasks,
    current_user: UserPublic = Depends(get_current_user),
):
    session_id = user_input.session_id or str(uuid.uuid4())
    set_session_id(session_id)
    _check_rate_limit(current_user.id)
    _verify_session_ownership(session_id, current_user.id)

    opik_tracer = OpikTracer(thread_id=session_id, project_name=settings.OPIK_PROJECT_NAME, tags=["chat"])
    result = await agent.ainvoke(
        {"question": user_input.query, "user_id": current_user.id},
        config={"configurable": {"thread_id": session_id}, "callbacks": [opik_tracer]},
    )

    background_tasks.add_task(opik_tracer.flush)
    background_tasks.add_task(_save_turn, session_id, current_user.id, user_input.query, result)

    return QueryResponse(
        answer=result["answer"],
        session_id=session_id,
        queries=result.get("queries", []),
        keywords=result.get("keywords", []),
        context=result.get("context", []),
        num_candidates=result.get("num_candidates", 0),
    )


@router.post("/ask/stream")
async def ask_stream(
    user_input: UserInput,
    background_tasks: BackgroundTasks,
    current_user: UserPublic = Depends(get_current_user),
):
    session_id = user_input.session_id or str(uuid.uuid4())
    set_session_id(session_id)
    _check_rate_limit(current_user.id)
    _verify_session_ownership(session_id, current_user.id)

    opik_tracer = OpikTracer(thread_id=session_id, project_name=settings.OPIK_PROJECT_NAME, tags=["chat"])
    background_tasks.add_task(opik_tracer.flush)

    async def event_generator():
        yield f"data: {json.dumps({'event': 'session', 'session_id': session_id})}\n\n"

        full_answer = ""
        tok_count = 0

        try:
            async for event in agent.astream_events(
                {"question": user_input.query, "user_id": current_user.id},
                config={"configurable": {"thread_id": session_id}, "callbacks": [opik_tracer]},
                version="v2",
            ):
                if event["event"] != "on_chat_model_stream":
                    continue
                if "internal_tool" in event.get("tags", []):
                    continue
                node_name = event.get("metadata", {}).get("langgraph_node")
                if node_name not in ("rag", "chitchat", "history"):
                    continue

                chunk = event["data"].get("chunk")
                if chunk and chunk.content and not chunk.tool_call_chunks:
                    full_answer += chunk.content
                    tok_count += 1
                    if tok_count % 3 == 0:
                        yield f"data: {json.dumps({'event': 'token', 'token': full_answer})}\n\n"
        except Exception as exc:
            logger.exception(f"Error during agent.astream_events for session {session_id}")
            yield f"data: {json.dumps({'event': 'error', 'detail': str(exc)})}\n\n"
            return

        if tok_count % 3 != 0 and full_answer:
            yield f"data: {json.dumps({'event': 'token', 'token': full_answer})}\n\n"

        try:
            state = await agent.aget_state({"configurable": {"thread_id": session_id}})
            vals = state.values if state else {}
            final_answer = vals.get("answer") or full_answer
            ctx = vals.get("context", [])
            queries = vals.get("queries", [])
            keywords = vals.get("keywords", [])
        except Exception:
            logger.exception(f"Error fetching final state for session {session_id}")
            final_answer, ctx, queries, keywords = full_answer, [], [], []

        result = {"answer": final_answer, "context": ctx, "queries": queries, "keywords": keywords}
        await asyncio.to_thread(_save_and_flush_turn, session_id, current_user.id, user_input.query, result)

        yield f"data: {json.dumps({'event': 'done', 'answer': final_answer, 'queries': queries, 'context': ctx})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


class SessionOut(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    context: str
    queries: str
    keywords: str
    created_at: str


@router.get("/chat/sessions", response_model=list[SessionOut])
async def list_sessions(current_user: UserPublic = Depends(get_current_user)):
    return get_sessions_by_user(current_user.id)


@router.get("/chat/session/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(session_id: str, current_user: UserPublic = Depends(get_current_user)):
    sess = get_session(session_id)
    if sess is None:
        return []
    if sess["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found.")
    return get_messages(session_id)


@router.delete("/chat/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(session_id: str, current_user: UserPublic = Depends(get_current_user)):
    if not db_delete_session(session_id, current_user.id):
        raise HTTPException(status_code=404, detail="Session not found.")


def _save_turn(session_id: str, user_id: str, question: str, result: dict) -> None:
    safe_q = redact_pii(question) if settings.REDACT_PII else question
    safe_a = redact_pii(result.get("answer", "")) if settings.REDACT_PII else result.get("answer", "")

    sess = get_session(session_id)
    if sess is None:
        create_session(session_id, user_id, safe_q[:80])
    elif not sess.get("title"):
        update_session_title(session_id, safe_q[:80])
    else:
        touch_session(session_id)

    queue_message(session_id=session_id, role="human", content=safe_q)
    queue_message(
        session_id=session_id,
        role="ai",
        content=safe_a,
        context=result.get("context", []),
        queries=result.get("queries", []),
        keywords=result.get("keywords", []),
    )


def _save_and_flush_turn(session_id: str, user_id: str, question: str, result: dict) -> None:
    _save_turn(session_id, user_id, question, result)
    flush()


@router.delete("/ask/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session_old(session_id: str, current_user: UserPublic = Depends(get_current_user)):
    await delete_chat_session(session_id, current_user)
