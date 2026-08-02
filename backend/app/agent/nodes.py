"""Single ReAct agent node — the entire pipeline.

The agent has a `retrieve_docs` tool. It decides:
- Answer directly from chat history / previous context (no tool call → ~4s)
- Call retrieve_docs to search documents → then answer (~8-15s)

This replaces the old multi-node pipeline (router → classify → retrieve → generate).
"""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.state import GraphState
from app.agent.tools import retrieve_docs
from app.config import settings
from app.core.llm import llm

_SYSTEM_PROMPT = (
    "You are a research assistant. You have a retrieve_docs tool.\n\n"
    "Default behavior: Call retrieve_docs for EVERY question to get "
    "context from the user's documents. Do NOT answer without calling it.\n\n"
    "Exception: If the user's question includes 'Here is the context I "
    "found earlier', read that context. If it fully answers the question, "
    "you may skip retrieve_docs. Otherwise, still call retrieve_docs.\n\n"
    "After retrieve_docs: If relevant text was found, answer from it. "
    "If nothing relevant was found, say you don't have context.\n"
    "Never invent facts."
)

_MAX_TOOL_CALLS = 3


async def react_agent_node(state: GraphState) -> dict:
    """ReAct agent with a `retrieve_docs` tool.

    The agent receives the question, chat history, and any previously retrieved
    context. It decides whether to answer directly or call the tool first.
    """
    question = state["question"]
    history = state.get("chat_history", []) or []
    prev_context = state.get("context", []) or []

    # Patch the user_id into the tool so it scopes retrieval correctly.
    retrieve_docs._user_id = state.get("user_id")
    llm_w_tools = llm.bind_tools([retrieve_docs])

    # --- Build message list ---
    messages: list = [SystemMessage(content=_SYSTEM_PROMPT)]

    # Inject previous context into the question itself (SystemMessages are
    # treated as instructions by the LLM and often ignored; appending to the
    # human message makes it part of the data the LLM reads).
    if prev_context:
        # Direct concatenation — no markers, no chunk labels.
        context_text = "\n".join(prev_context)
        augmented_question = f"{question}\n\nHere is the context I found earlier:\n{context_text}"
    else:
        augmented_question = question

    # Chat history (prior Q&A turns).
    messages.extend(history)
    messages.append(HumanMessage(content=augmented_question))

    # --- ReAct loop ---
    raw_contexts: list[str] = []
    tool_queries: list[str] = []

    for attempt in range(_MAX_TOOL_CALLS):
        # astream_events intercepts token callbacks even with invoke.
        response = await asyncio.to_thread(llm_w_tools.invoke, messages)
        messages.append(response)

        if not response.tool_calls:
            break  # Final answer — no more tool calls needed.

        # Execute each tool call.
        for tc in response.tool_calls:
            if tc["name"] == "retrieve_docs":
                query = tc["args"].get("query", "")
                tool_queries.append(query)
                result = await asyncio.to_thread(retrieve_docs.invoke, tc["args"])
                raw_contexts.append(result)
                messages.append(
                    ToolMessage(content=result, tool_call_id=tc["id"])
                )

    # The last AIMessage is the final answer.
    final: AIMessage | None = None
    for m in reversed(messages):
        if isinstance(m, AIMessage) and not m.tool_calls:
            final = m
            break

    answer = final.content if final else ""

    # Build chat_history for persistence — store raw turns (Human + AI).
    # System messages and tool internals are ephemeral.
    persisted = [
        HumanMessage(content=question),
        AIMessage(content=answer),
    ]

    # Preserve previous context when agent answered from history (no tool call).
    # Without this, follow-ups lose all context and re-answer "don't know."
    if not raw_contexts and prev_context:
        preserved_context = prev_context
    else:
        preserved_context = raw_contexts

    return {
        "answer": answer,
        "chat_history": persisted,
        "context": preserved_context,
        "queries": tool_queries,
        "keywords": [],
        "num_candidates": len(preserved_context),
    }
