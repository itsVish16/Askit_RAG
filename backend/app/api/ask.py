"""Ask endpoint (POST /ask) + streaming (POST /ask/stream) + chat history CRUD."""

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
from app.core.logger import set_session_id
from app.core.security import UserPublic
from app.db.chat import (
    create_session,
    get_messages,
    get_session,
    get_sessions_by_user,
    queue_message,
    update_session_title,
)
from app.db.chat import (
    delete_session as db_delete_session,
)

router = APIRouter()

# In-process token-bucket rate limiter.
_session_hits: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(session_id: str) -> None:
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
    query: str = Field(..., max_length=settings.MAX_QUERY_LEN)
    session_id: str | None = None
    user_id: str | None = None  # deprecated — retrieval is always scoped to JWT user

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


# ---------- standard (non-streaming) ask ----------


@router.post("/ask", response_model=QueryResponse)
async def ask_query(
    user_input: UserInput,
    background_tasks: BackgroundTasks,
    current_user: UserPublic = Depends(get_current_user),
):
    session_id = user_input.session_id or str(uuid.uuid4())
    set_session_id(session_id)
    _check_rate_limit(session_id)

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


# ---------- streaming ask ----------


@router.post("/ask/stream")
async def ask_stream(
    user_input: UserInput,
    background_tasks: BackgroundTasks,
    current_user: UserPublic = Depends(get_current_user),
):
    session_id = user_input.session_id or str(uuid.uuid4())
    set_session_id(session_id)
    _check_rate_limit(session_id)

    opik_tracer = OpikTracer(thread_id=session_id, project_name=settings.OPIK_PROJECT_NAME, tags=["chat"])
    background_tasks.add_task(opik_tracer.flush)

    async def event_generator():
        import logging
        log = logging.getLogger("ask_stream")
        log.info(f"Starting event_generator for session {session_id}")
        
        # Send session event first so the client knows the id.
        yield f"data: {json.dumps({'event': 'session', 'session_id': session_id})}\n\n"

        full_answer = ""
        tok_count = 0

        # Stream events from the agent graph.
        try:
            async for event in agent.astream_events(
                {"question": user_input.query, "user_id": current_user.id},
                config={"configurable": {"thread_id": session_id}, "callbacks": [opik_tracer]},
                version="v2",
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    # Filter out internal LLM calls (e.g. query expansion)
                    if "internal_tool" in event.get("tags", []):
                        continue
                    
                    # Only stream tokens from the generation nodes.
                    node_name = event.get("metadata", {}).get("langgraph_node")
                    if node_name not in ["rag", "chitchat", "history"]:
                        continue

                    chunk = event["data"].get("chunk")
                    if chunk and chunk.content and not chunk.tool_call_chunks:
                        full_answer += chunk.content
                        tok_count += 1
                        if tok_count % 3 == 0:  # batch tokens for fewer SSE messages
                            yield f"data: {json.dumps({'event': 'token', 'token': full_answer})}\n\n"
        except Exception as e:
            log.error(f"Error during agent.astream_events: {e}", exc_info=True)

        log.info(f"astream_events completed. Fetching state for session {session_id}")

        # Get the full final state from the checkpointer.
        try:
            state = await agent.aget_state({"configurable": {"thread_id": session_id}})
            final_answer = (state.values.get("answer") or full_answer) if state else full_answer
            ctx = state.values.get("context", []) if state else []
            queries = state.values.get("queries", []) if state else []
        except Exception as e:
            log.error(f"Error getting state: {e}", exc_info=True)
            final_answer = full_answer
            ctx = []
            queries = []

        # Persist to SQLite.
        from app.db.chat import flush
        result = {"answer": final_answer, "context": ctx, "queries": queries, "keywords": []}
        _save_turn(session_id, current_user.id, user_input.query, result)
        flush()
        
        log.info(f"Database flushed for session {session_id}. Yielding done event.")

        # Send the complete answer and done marker.
        yield f"data: {json.dumps({'event': 'done', 'answer': final_answer, 'queries': queries, 'context': ctx})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------- chat history ----------


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
    context: str  # JSON string
    queries: str  # JSON string
    keywords: str  # JSON string
    created_at: str


@router.get("/chat/sessions", response_model=list[SessionOut])
async def list_sessions(current_user: UserPublic = Depends(get_current_user)):
    """List the current user's chat sessions (newest first)."""
    return get_sessions_by_user(current_user.id)


@router.get("/chat/session/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(session_id: str, current_user: UserPublic = Depends(get_current_user)):
    """Get all messages for a session. Verifies ownership."""
    sess = get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if sess["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found.")
    return get_messages(session_id)


@router.delete("/chat/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(session_id: str, current_user: UserPublic = Depends(get_current_user)):
    """Delete a session and its messages. Verifies ownership."""
    ok = db_delete_session(session_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found.")


# ---------- helpers ----------


def _save_turn(session_id: str, user_id: str, question: str, result: dict) -> None:
    """Persist a Q&A turn to the chat store and ensure the session exists."""
    # Ensure session row exists.
    sess = get_session(session_id)
    if sess is None:
        create_session(session_id, user_id, question[:80])
    else:
        # Update title from first question (if empty).
        if not sess.get("title"):
            update_session_title(session_id, question[:80])

    # Queue messages for periodic flush.
    queue_message(session_id=session_id, role="human", content=question)
    queue_message(
        session_id=session_id,
        role="ai",
        content=result.get("answer", ""),
        context=result.get("context", []),
        queries=result.get("queries", []),
        keywords=result.get("keywords", []),
    )


# Keep the old DELETE for backward compat.
@router.delete("/ask/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session_old(session_id: str, current_user: UserPublic = Depends(get_current_user)):
    await delete_chat_session(session_id, current_user)
