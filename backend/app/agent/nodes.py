"""Deterministic retrieval and generation pipeline.

Replaces the old ReAct loop to eliminate redundant LLM calls and reduce latency.
Always retrieves documents for the query concurrently, then generates an answer in one LLM call.
"""

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.state import GraphState
from app.agent.tools import retrieve_docs_async
from app.config import settings
from app.core.llm import llm, router_llm
from app.core.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful research assistant. Answer the user's question based "
    "on the provided document context. If the context does not contain the answer, "
    "say you don't know. Do not invent facts."
)

class RouteDecision(BaseModel):
    route: Literal["rag", "chitchat"] = Field(
        description="Choose 'rag' if the user is asking a question that requires domain knowledge or document retrieval. Choose 'chitchat' if the user is just saying hello, giving a casual greeting, or asking a generic conversational question that requires no external knowledge."
    )

async def router_node(state: GraphState) -> dict:
    """Classifies the user query to decide whether to run full RAG or fast chitchat."""
    question = state["question"]
    
    if not settings.ROUTE_ENABLED:
        return {"route": "rag"}
        
    # Use LLM to classify intent
    # Fast lightweight prompt
    messages = [
        SystemMessage(content=(
            "You are a strict routing assistant. Your job is to classify user queries.\n"
            "Route to 'rag' for ANY question asking for information, facts, data, projects, or documents.\n"
            "Route to 'chitchat' ONLY for basic conversational greetings (e.g., 'hello', 'hi', 'how are you').\n"
            "When in doubt, always choose 'rag'."
        )),
        HumanMessage(content=question)
    ]
    
    try:
        classifier = router_llm.with_config(tags=["router"]).with_structured_output(RouteDecision)
        decision = await classifier.ainvoke(messages)
        return {"route": decision.route}
    except Exception as exc:
        logger.warning(f"[router] classification failed: {exc} — falling back to rag")
        return {"route": "rag"}


async def chitchat_node(state: GraphState) -> dict:
    """Fast-path generation for conversational queries (skips retrieval entirely)."""
    question = state["question"]
    history = state.get("chat_history", []) or []
    
    messages = [
        SystemMessage(content="You are a helpful and friendly AI assistant. Keep your answer brief and conversational. You do not have access to external documents for this response.")
    ]
    messages.extend(history)
    messages.append(HumanMessage(content=question))
    
    response = await llm.with_config({"run_name": "final_generation"}).ainvoke(messages)
    answer = response.content
    
    persisted = [
        HumanMessage(content=question),
        AIMessage(content=answer),
    ]
    
    return {
        "answer": answer,
        "chat_history": persisted,
        "context": [],
        "queries": [],
        "keywords": [],
        "num_candidates": 0,
    }

async def rag_agent_node(state: GraphState) -> dict:
    """Retrieves context and generates an answer in a single step."""
    question = state["question"]
    history = state.get("chat_history", []) or []
    user_id = state.get("user_id")

    # Fetch context concurrently
    context_text, queries, keywords = await retrieve_docs_async(question, user_id)
    
    # Store raw context chunks for the UI response
    found_docs = context_text != "No relevant documents found." and context_text != "No documents available (user not set)."
    raw_contexts = [context_text] if found_docs else []

    # Build prompt
    augmented_question = (
        f"Context:\n{context_text}\n\n"
        f"Question: {question}"
    )

    messages = [SystemMessage(content=_SYSTEM_PROMPT)]
    messages.extend(history)
    messages.append(HumanMessage(content=augmented_question))

    # Single async LLM generation
    response = await llm.with_config({"run_name": "final_generation"}).ainvoke(messages)
    answer = response.content

    persisted = [
        HumanMessage(content=question),
        AIMessage(content=answer),
    ]

    return {
        "answer": answer,
        "chat_history": persisted,
        "context": raw_contexts,
        "queries": queries,
        "keywords": keywords,
        "num_candidates": len(raw_contexts),
    }
