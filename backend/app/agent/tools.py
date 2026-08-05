"""Async document retrieval tools."""

import asyncio
from pydantic import BaseModel, Field

from app.config import settings
from app.core.llm import llm
from app.core.prompts import SEARCH_EXPANSION_PROMPT
from app.db.retrievers import bm25_candidates_from_keywords, rerank_texts, retrieve_candidates


class SearchExpansion(BaseModel):
    is_complex: bool = Field(description="True if the query is complex and requires multi-query expansion. False if it's a simple query.")
    keywords: list[str] = Field(description="5-8 specific keywords, entities, and synonyms for lexical search.")
    variants: list[str] = Field(description="If is_complex is True, generate 3 alternative versions of the question. If False, leave empty.")

async def generate_search_expansion(query: str) -> SearchExpansion:
    """Uses the LLM to analyze query complexity, generate keywords, and optionally generate multi-query variants in one call."""
    res = await llm.with_structured_output(SearchExpansion).with_config(tags=["internal_tool"]).ainvoke(
        SEARCH_EXPANSION_PROMPT.format_messages(question=query)
    )
    return res

async def retrieve_docs_async(query: str, user_id: str | None) -> tuple[str, list[str], list[str]]:
    """Search the user's uploaded documents for relevant information concurrently."""
    if not user_id:
        return "No documents available (user not set).", [query], []

    k = settings.K_RETRIEVE

    # 1. Expand query and extract keywords in a single structured call
    expansion = await generate_search_expansion(query)
    
    # Extract keywords
    keywords = [k.strip() for k in expansion.keywords if k.strip()]
    
    # 2. Determine queries to search
    all_queries = [query]
    if expansion.is_complex and expansion.variants:
        # Take up to MULTI_QUERY_N variants
        variants = expansion.variants[:settings.MULTI_QUERY_N]
        # Ensure original query is in variants and deduplicate
        all_queries = list(dict.fromkeys([query] + variants))

    # 3. Retrieve candidates for all queries and keywords concurrently
    tasks = []
    for q in all_queries:
        tasks.append(asyncio.create_task(retrieve_candidates(q, k, user_id)))
    
    if keywords:
        tasks.append(asyncio.create_task(bm25_candidates_from_keywords(keywords, k, user_id)))
        
    results = await asyncio.gather(*tasks)
    
    # 4. Deduplicate
    pool = set()
    for res in results:
        for chunk in res:
            pool.add(chunk)
            
    pool_list = list(pool)
    
    # 5. Rerank
    reranked = await asyncio.to_thread(rerank_texts, query, pool_list, settings.K_FINAL)
    
    if not reranked:
        return "No relevant documents found.", all_queries, keywords

    context_text = "\n\n---\n\n".join(
        f"Chunk {i + 1}: {chunk}" for i, chunk in enumerate(reranked)
    )
    
    return context_text, all_queries, keywords
