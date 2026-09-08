import asyncio

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import settings
from app.core.llm import llm
from app.core.logger import get_logger
from app.core.prompts import SEARCH_EXPANSION_PROMPT
from app.db.retrievers import bm25_candidates_from_keywords, rerank_texts, retrieve_candidates

logger = get_logger(__name__)


@tool
def retrieve_documents(query: str) -> str:
    """Search the user's uploaded documents for passages and facts relevant to the query."""
    return query


class SearchExpansion(BaseModel):
    is_complex: bool = Field(description="True if the query is complex and requires multi-query expansion. False if it's a simple query.")
    keywords: list[str] = Field(description="5-8 specific keywords, entities, and synonyms for lexical search.")
    variants: list[str] = Field(description="If is_complex is True, generate 3 alternative versions of the question. If False, leave empty.")

async def generate_search_expansion(query: str) -> SearchExpansion:
    """Uses the LLM to analyze query complexity, generate keywords, and optionally generate multi-query variants in one call."""
    try:
        res = await llm.with_structured_output(SearchExpansion).with_config(tags=["internal_tool"]).ainvoke(
            SEARCH_EXPANSION_PROMPT.format_messages(question=query)
        )
        return res
    except Exception as exc:
        logger.warning(f"[search_expansion] structured call failed: {exc} — falling back to single-query baseline")
        clean_words = [w.strip() for w in query.split() if len(w.strip()) > 3]
        return SearchExpansion(is_complex=False, keywords=clean_words[:6], variants=[])

async def retrieve_docs_async(query: str, user_id: str | None) -> tuple[str, list[str], list[str], list[str]]:
    """Search documents for relevant information concurrently (user-scoped or shared corpus)."""
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
    
    # 4. Deduplicate while preserving rank order from dense & BM25 retrieval
    seen = set()
    ordered_pool: list[str] = []
    for res in results:
        for chunk in res:
            c = chunk.strip() if isinstance(chunk, str) else str(chunk).strip()
            if c and c not in seen:
                seen.add(c)
                ordered_pool.append(c)
            
    # Cap candidate pool to top 20 before cloud reranking (saves tokens & latency)
    candidates_to_rerank = ordered_pool[:20]
    
    # 5. Rerank
    reranked = await asyncio.to_thread(rerank_texts, query, candidates_to_rerank, settings.K_FINAL)
    
    if not reranked:
        return "No relevant documents found.", all_queries, keywords, []

    context_text = "\n\n---\n\n".join(
        f"Chunk {i + 1}: {chunk}" for i, chunk in enumerate(reranked)
    )
    
    return context_text, all_queries, keywords, reranked
