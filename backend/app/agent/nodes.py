"""Deterministic retrieval and generation pipeline.

Replaces the old ReAct loop to eliminate redundant LLM calls and reduce latency.
Always retrieves documents for the query concurrently, then generates an answer in one LLM call.
"""

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from app.agent.state import GraphState
from app.agent.tools import retrieve_docs_async, retrieve_documents
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

_REACT_SYSTEM_PROMPT = (
    "You are a helpful research assistant operating with a ReAct (Reasoning and Acting) workflow.\n"
    "You have access to the `retrieve_documents` tool to search the user's uploaded documents.\n\n"
    "Guidelines:\n"
    "1. When the user's question requires facts, document excerpts, or specific information from their files, "
    "invoke `retrieve_documents` with a targeted search query.\n"
    "2. Once you observe the retrieved document chunks, synthesize a direct, well-grounded response citing relevant details.\n"
    "3. If the retrieved context is insufficient or irrelevant, state clearly that the uploaded documents do not contain the answer. "
    "Do not invent or extrapolate facts.\n"
    "4. If no external documents are needed (e.g. conversational greetings or questions about the immediate conversation), answer directly."
)


async def rag_reasoning_node(state: GraphState) -> dict:
    """ReAct agent reasoning step: evaluates conversation history and tool observations to decide action or answer."""
    question = state["question"]
    history = state.get("chat_history", []) or []
    current_messages = state.get("messages", []) or []

    if not current_messages:
        working_messages = [SystemMessage(content=_REACT_SYSTEM_PROMPT)]
        working_messages.extend(history[-6:])
        working_messages.append(HumanMessage(content=question))
    else:
        working_messages = list(current_messages)

    llm_with_tools = llm.bind_tools([retrieve_documents]).with_config({"run_name": "final_generation"})
    response = await llm_with_tools.ainvoke(working_messages)

    update = {"messages": [response]}
    if not (hasattr(response, "tool_calls") and response.tool_calls):
        # Final answer produced (no further tool actions needed)
        answer = response.content or ""
        update["answer"] = answer
        update["chat_history"] = [
            HumanMessage(content=question),
            AIMessage(content=answer),
        ]
    return update


async def execute_tools_node(state: GraphState) -> dict:
    """ReAct Action step: executes the retrieve_documents tool calls and returns observations."""
    last_msg = state["messages"][-1]
    tool_messages = []
    accumulated_context = list(state.get("context", []) or [])
    accumulated_queries = list(state.get("queries", []) or [])
    accumulated_keywords = list(state.get("keywords", []) or [])
    user_id = state.get("user_id")

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            if tc.get("name") == "retrieve_documents":
                q = tc.get("args", {}).get("query", state["question"])
                context_text, queries, keywords, chunks = await retrieve_docs_async(q, user_id)
                tool_messages.append(
                    ToolMessage(
                        content=context_text,
                        name=tc["name"],
                        tool_call_id=tc["id"],
                    )
                )
                for chunk in chunks:
                    if chunk not in accumulated_context:
                        accumulated_context.append(chunk)
                for query in queries:
                    if query not in accumulated_queries:
                        accumulated_queries.append(query)
                for kw in keywords:
                    if kw not in accumulated_keywords:
                        accumulated_keywords.append(kw)

    return {
        "messages": tool_messages,
        "context": accumulated_context,
        "queries": accumulated_queries,
        "keywords": accumulated_keywords,
        "num_candidates": len(accumulated_context),
    }


def should_continue_rag(state: GraphState) -> str:
    """Checks if the ReAct agent requested tool execution or reached the final answer."""
    messages = state.get("messages", [])
    if not messages:
        return "end"
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "end"


# Backwards-compatibility alias
rag_agent_node = rag_reasoning_node

