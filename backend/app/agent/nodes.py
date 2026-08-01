from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.state import GraphState
from app.config import settings
from app.core.llm import llm
from app.core.prompts import KEYWORD_EXTRACTION_PROMPT, MULTI_QUERY_PROMPT, RAG_PROMPT
from app.core.redact import redact_pii
from app.db.retrievers import (
    bm25_candidates_from_keywords,
    rerank_texts,
    retrieve_candidates,
)


def multi_query_node(state: GraphState):
    """Expand the question into N domain-aware variants for wider recall."""
    chain = MULTI_QUERY_PROMPT | llm
    response = chain.invoke({"question": state["question"], "n": settings.MULTI_QUERY_N})
    variants = [line.strip() for line in response.content.splitlines() if line.strip()]
    queries = [state["question"], *variants]  # keep original phrasing too
    return {"queries": queries}


def keyword_node(state: GraphState):
    """Extract entities/synonyms so BM25 gets tokens it can actually match."""
    chain = KEYWORD_EXTRACTION_PROMPT | llm
    response = chain.invoke({"question": state["question"]})
    keywords = [line.strip() for line in response.content.splitlines() if line.strip()]
    return {"keywords": keywords}


def retrieve_node(state: GraphState):
    """Pool dense + BM25 candidates from every variant, then rerank once."""
    user_id = state.get("user_id")
    pool: list[str] = []

    for q in state["queries"]:
        pool.extend(retrieve_candidates(q, k_retrieve=settings.K_RETRIEVE, user_id=user_id))
    pool.extend(
        bm25_candidates_from_keywords(state["keywords"], k=settings.K_RETRIEVE, user_id=user_id)
    )

    seen: set[str] = set()
    pool = [t for t in pool if not (t in seen or seen.add(t))]
    context_list = rerank_texts(state["question"], pool, k_final=settings.K_FINAL)
    return {"context": context_list, "num_candidates": len(pool)}


def generate_node(state: GraphState):
    """Grounded answer over retrieved context, with chat history for follow-ups."""
    chain = RAG_PROMPT | llm
    history: list[BaseMessage] = state.get("chat_history", []) or []
    response = chain.invoke(
        {"context": "\n\n".join(state["context"]), "question": state["question"], "history": history}
    )

    # Persist this turn into chat_history. PII is redacted BEFORE persistence
    # so the checkpointer never stores verbatim PHI; the LLM saw the original.
    persisted_question = (
        redact_pii(state["question"]) if settings.REDACT_PII else state["question"]
    )
    new_turn = [HumanMessage(content=persisted_question), AIMessage(content=response.content)]
    return {"answer": response.content, "chat_history": new_turn}
