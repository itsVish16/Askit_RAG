"""LangGraph routing and generation nodes."""

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.state import GraphState
from app.agent.tools import retrieve_docs_async
from app.config import settings
from app.core.llm import llm, router_llm
from app.core.logger import get_logger
from app.core.prompts import RAG_SYSTEM_TEXT
from app.core.redact import redact_pii

logger = get_logger(__name__)


class RouteDecision(BaseModel):
    route: Literal["rag", "history", "chitchat"] = Field(
        description=(
            "'chitchat' for greetings/pleasantries; "
            "'history' if answerable solely from prior conversation turns; "
            "'rag' if document retrieval is needed."
        )
    )


def _maybe_redact(text: str) -> str:
    return redact_pii(text) if settings.REDACT_PII else text


def _build_persisted_turn(question: str, answer: str) -> list:
    return [
        HumanMessage(content=_maybe_redact(question)),
        AIMessage(content=_maybe_redact(answer)),
    ]


async def router_node(state: GraphState) -> dict:
    """Route query to 'rag', 'history', or 'chitchat'."""
    question = state["question"]
    history = state.get("chat_history", []) or []

    if not settings.ROUTE_ENABLED:
        return {"route": "rag"}

    history_lines = []
    for msg in history[-6:]:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        history_lines.append(f"{role}: {str(msg.content)[:300]}")
    history_context = "\n".join(history_lines) if history_lines else "None"

    messages = [
        SystemMessage(
            content=(
                "Classify the user's question for a document Q&A assistant.\n"
                "- 'chitchat': greetings or pleasantries.\n"
                "- 'history': repeats, summaries, or clarifications answerable strictly from prior turns.\n"
                "- 'rag': any new factual question requiring document lookup.\n"
                "When in doubt, choose 'rag'."
            )
        ),
        HumanMessage(content=f"Prior Conversation:\n{history_context}\n\nQuestion: {question}"),
    ]

    try:
        classifier = router_llm.with_config(tags=["router"]).with_structured_output(RouteDecision)
        decision = await classifier.ainvoke(messages)
        if decision.route == "history" and not history:
            return {"route": "rag"}
        return {"route": decision.route}
    except Exception as exc:
        logger.warning(f"[router] classification failed: {exc} — falling back to rag")
        return {"route": "rag"}


async def history_node(state: GraphState) -> dict:
    """Answer follow-up questions directly from conversation history."""
    question = state["question"]
    history = state.get("chat_history", []) or []

    messages = [
        SystemMessage(
            content=(
                "Answer the user's question concisely using only the conversation history. "
                "Do not invent facts."
            )
        ),
        *history,
        HumanMessage(content=question),
    ]
    response = await llm.with_config({"run_name": "final_generation"}).ainvoke(messages)
    answer = response.content

    return {
        "answer": answer,
        "chat_history": _build_persisted_turn(question, answer),
        "context": [],
        "queries": [],
        "keywords": [],
        "num_candidates": 0,
    }


async def chitchat_node(state: GraphState) -> dict:
    """Handle conversational pleasantries without document retrieval."""
    question = state["question"]
    history = state.get("chat_history", []) or []

    messages = [
        SystemMessage(
            content="You are a concise, friendly assistant. Keep replies brief; no document context is loaded for this turn."
        ),
        *history,
        HumanMessage(content=question),
    ]
    response = await llm.with_config({"run_name": "final_generation"}).ainvoke(messages)
    answer = response.content

    return {
        "answer": answer,
        "chat_history": _build_persisted_turn(question, answer),
        "context": [],
        "queries": [],
        "keywords": [],
        "num_candidates": 0,
    }


async def rag_agent_node(state: GraphState) -> dict:
    """Retrieve ranked chunks and generate a grounded answer."""
    question = state["question"]
    history = state.get("chat_history", []) or []
    user_id = state.get("user_id")
    allow_shared = state.get("corpus_scope") == "shared"

    chunks, queries, keywords, total_candidates = await retrieve_docs_async(
        question, user_id, allow_shared=allow_shared
    )

    if chunks:
        context_text = "\n\n---\n\n".join(f"Chunk {i + 1}: {c}" for i, c in enumerate(chunks))
    elif not user_id and not allow_shared:
        context_text = "No documents available (user not set)."
    else:
        context_text = "No relevant documents found."

    system_prompt = RAG_SYSTEM_TEXT.format(context=context_text)
    messages = [
        SystemMessage(content=system_prompt),
        *history,
        HumanMessage(content=question),
    ]

    response = await llm.with_config({"run_name": "final_generation"}).ainvoke(messages)
    answer = response.content

    return {
        "answer": answer,
        "chat_history": _build_persisted_turn(question, answer),
        "context": chunks,
        "queries": queries,
        "keywords": keywords,
        "num_candidates": total_candidates,
    }
