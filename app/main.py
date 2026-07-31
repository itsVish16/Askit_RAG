import os
import uuid
from typing import TypedDict

import uvicorn
from fastapi import FastAPI
from langgraph.graph import END, StateGraph
from opik.integrations.langchain import OpikTracer
from pydantic import BaseModel

from app.config import settings
from app.core.llm import llm
from app.core.prompts import (
    KEYWORD_EXTRACTION_PROMPT,
    MULTI_QUERY_PROMPT,
    RAG_PROMPT,
)
from app.db.retrievers import (
    bm25_candidates_from_keywords,
    get_bm25_retriever,
    rerank_texts,
    retrieve_candidates,
)

os.environ["OPIK_PROJECT_NAME"] = settings.OPIK_PROJECT_NAME


app = FastAPI(title="Askit RAG", version="1.0.0")


@app.on_event("startup")
async def startup_build_bm25():
    """Pre-build the BM25 index once at startup, not on first query.

    Without this, the first request pays ~2s to scroll all docs and build
    the keyword index. We also touch the cross-encoder so the first
    rerank pass doesn't pay model-load latency either.
    """
    print("Pre-building BM25 index + warming reranker at startup...")
    get_bm25_retriever(k=settings.K_RETRIEVE)
    rerank_texts("warmup", ["warmup document"], k_final=1)
    print("Retrieval stack ready.")


class UserInput(BaseModel):
    query: str
    # Optional: reuse to group a conversation under one Opik thread.
    session_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    session_id: str
    queries: list[str]
    keywords: list[str]
    context: list[str]
    num_candidates: int


class GraphState(TypedDict, total=False):
    question: str
    queries: list[str]  # original + expanded variants (multi-query node)
    keywords: list[str]  # extracted domain terms for BM25 (keyword node)
    context: list[str]
    num_candidates: int
    answer: str


def multi_query_node(state: GraphState):
    """Expand the user's question into several diverse search queries.

    Vague questions ('What was the focus of the study?') fail retrieval.
    An LLM rewrites them into N specific, domain-aware variants; we then
    retrieve with ALL of them and pool the results before ONE rerank pass.
    """
    print("-- Node: EXPANDING QUERIES --")
    chain = MULTI_QUERY_PROMPT | llm
    response = chain.invoke({"question": state["question"], "n": settings.MULTI_QUERY_N})
    variants = [line.strip() for line in response.content.splitlines() if line.strip()]
    # Always include the original question so the exact phrasing is searched too.
    queries = [state["question"], *variants]
    print(f"   expanded to {len(queries)} queries")
    return {"queries": queries}


def keyword_node(state: GraphState):
    """Extract domain keywords so BM25 gets tokens it can actually match.

    BM25 is lexical: 'how does COVID spread' matches nothing, while the corpus
    says 'SARS-CoV-2 transmission via respiratory droplets'. An LLM extracts
    the entities + scientific synonyms that close that vocabulary gap.
    """
    print("-- Node: EXTRACTING KEYWORDS --")
    chain = KEYWORD_EXTRACTION_PROMPT | llm
    response = chain.invoke({"question": state["question"]})
    keywords = [line.strip() for line in response.content.splitlines() if line.strip()]
    print(f"   extracted {len(keywords)} keywords: {keywords}")
    return {"keywords": keywords}


def retrieve_node(state: GraphState):
    """Retrieve CANDIDATES (no rerank) with every expanded query, pooled.

    Then rerank the whole pool ONCE against the ORIGINAL question — the
    cross-encoder scores true relevance and cuts it to the best k_final.
    """
    print("-- Node: RETRIEVING CONTEXT --")
    pool: list[str] = []

    # Dense + BM25 candidates from each expanded multi-query variant.
    for q in state["queries"]:
        pool.extend(retrieve_candidates(q, k_retrieve=settings.K_RETRIEVE))

    # BM25 with the EXTRACTED KEYWORDS — the lexical engine gets domain terms.
    pool.extend(bm25_candidates_from_keywords(state["keywords"], k=settings.K_RETRIEVE))

    seen: set[str] = set()
    pool = [t for t in pool if not (t in seen or seen.add(t))]
    print(f"   pooled {len(pool)} unique candidates, reranking to {settings.K_FINAL}")
    context_list = rerank_texts(state["question"], pool, k_final=settings.K_FINAL)
    return {"context": context_list, "num_candidates": len(pool)}


def generate_node(state: GraphState):
    print("-- Node: GENERATING ANSWER --")
    chain = RAG_PROMPT | llm
    response = chain.invoke(
        {"context": "\n\n".join(state["context"]), "question": state["question"]}
    )
    return {"answer": response.content}


workflow = StateGraph(GraphState)
workflow.add_node("multi_query", multi_query_node)
workflow.add_node("keywords", keyword_node)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("generate", generate_node)
workflow.set_entry_point("multi_query")
workflow.add_edge("multi_query", "keywords")
workflow.add_edge("keywords", "retrieve")
workflow.add_edge("retrieve", "generate")
workflow.add_edge("generate", END)

app_agent = workflow.compile()


@app.post("/ask", response_model=QueryResponse)
async def ask_query(user_input: UserInput):
    session_id = user_input.session_id or str(uuid.uuid4())

    # One Opik trace per request: OpikTracer captures every LangChain run
    # (each node chain, each LLM call, each retriever) as spans, and
    # thread_id groups all requests of a conversation under one thread.
    opik_tracer = OpikTracer(thread_id=session_id)

    result = app_agent.invoke(
        {"question": user_input.query}, config={"callbacks": [opik_tracer]}
    )
    opik_tracer.flush()  # don't lose the trace if the process is short-lived
    return QueryResponse(
        answer=result["answer"],
        session_id=session_id,
        queries=result["queries"],
        keywords=result["keywords"],
        context=result["context"],
        num_candidates=result["num_candidates"],
    )


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
