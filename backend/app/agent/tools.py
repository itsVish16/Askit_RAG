"""Async hybrid document retrieval and query expansion."""

import asyncio

from pydantic import BaseModel, Field

from app.config import settings
from app.core.llm import llm
from app.core.prompts import SEARCH_EXPANSION_PROMPT
from app.db.retrievers import bm25_candidates_from_keywords, rerank_texts, retrieve_candidates


class SearchExpansion(BaseModel):
    is_complex: bool = Field(
        description="True if the query requires multi-query expansion, False for simple lookups."
    )
    keywords: list[str] = Field(
        description="5-8 specific keywords, entities, and synonyms for lexical search."
    )
    variants: list[str] = Field(
        description="3 alternative phrasings if is_complex is True, else empty."
    )


async def generate_search_expansion(query: str) -> SearchExpansion:
    """Analyze query complexity, extract BM25 keywords, and generate query variants."""
    return await llm.with_structured_output(SearchExpansion).with_config(
        tags=["internal_tool"]
    ).ainvoke(SEARCH_EXPANSION_PROMPT.format_messages(question=query))


async def retrieve_docs_async(
    query: str,
    user_id: str | None,
    *,
    allow_shared: bool = False,
) -> tuple[list[str], list[str], list[str], int]:
    """Retrieve and rerank document chunks.

    Returns (reranked_chunks, expanded_queries, keywords, total_candidate_count).
    """
    if not user_id and not allow_shared:
        return [], [query], [], 0

    k = settings.K_RETRIEVE
    expansion = await generate_search_expansion(query)
    keywords = [kw.strip() for kw in expansion.keywords if kw.strip()]

    all_queries = [query]
    if expansion.is_complex and expansion.variants:
        variants = expansion.variants[: settings.MULTI_QUERY_N]
        all_queries = list(dict.fromkeys([query] + variants))

    scope_user = None if allow_shared else user_id
    tasks = [asyncio.create_task(retrieve_candidates(q, k, scope_user)) for q in all_queries]
    if keywords:
        tasks.append(asyncio.create_task(bm25_candidates_from_keywords(keywords, k, scope_user)))

    results = await asyncio.gather(*tasks)

    pool: list[str] = list(dict.fromkeys(chunk for res in results for chunk in res))
    if not pool:
        return [], all_queries, keywords, 0

    reranked = await asyncio.to_thread(rerank_texts, query, pool, settings.K_FINAL)
    return reranked, all_queries, keywords, len(pool)
