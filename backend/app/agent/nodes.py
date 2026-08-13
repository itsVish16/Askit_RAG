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
    route: Literal["rag", "history", "chitchat"] = Field(
        description=(
            "Choose 'chitchat' for basic conversational greetings (e.g. 'hello', 'hi', 'thanks', 'bye'). "
            "Choose 'history' if the user's question can be directly and accurately answered from the existing conversation history alone (e.g., repeating a previous question, asking for clarification on the previous answer, summarizing what was just discussed, or asking follow-ups about topics already covered in the chat). "
            "Choose 'rag' if the user is asking for new information, facts, data, or documents that are NOT already answered or present in the conversation history."
        )
    )

async def router_node(state: GraphState) -> dict:
    """Classifies the user query to decide whether to run full RAG, memory-assisted history answer, or fast chitchat."""
    question = state["question"]
    history = state.get("chat_history", []) or []
    
    if not settings.ROUTE_ENABLED:
        return {"route": "rag"}
        
    # Format recent history (up to last 6 turns) so router has context
    history_summary = []
    for msg in history[-6:]:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        content_preview = str(msg.content)[:300]
        history_summary.append(f"{role}: {content_preview}")
        
    history_context = "\n".join(history_summary) if history_summary else "None (Start of conversation)"
    
    messages = [
        SystemMessage(content=(
            "You are a strict routing assistant for a document Q&A assistant.\n"
            "Analyze the user's new question in light of the prior conversation history.\n\n"
            "Routing Rules:\n"
            "1. 'chitchat': Basic casual greetings or pleasantries (e.g., 'hello', 'hi', 'how are you', 'thank you', 'who are you').\n"
            "2. 'history': Use this if the user's question is a repeat, summary, clarification, or follow-up that can be answered directly from the previous Assistant responses in the conversation history without searching the document database again.\n"
            "3. 'rag': Use this if the user is asking about new facts, topics, or documents not found in the conversation history.\n"
            "When in doubt, choose 'rag'."
        )),
        HumanMessage(content=(
            f"Prior Conversation History:\n{history_context}\n\n"
            f"New User Question: {question}"
        ))
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
    """Answers follow-up / repeat / summary questions directly from conversation history (skipping vector retrieval)."""
    question = state["question"]
    history = state.get("chat_history", []) or []
    
    messages = [
        SystemMessage(content=(
            "You are a helpful research assistant. Answer the user's question directly based on the "
            "conversation history. Be concise, accurate, and helpful. Do not invent facts."
        ))
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
