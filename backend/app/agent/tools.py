"""ReAct agent tool: `retrieve_docs` — the agent calls this when it needs
fresh context from the user's uploaded documents.

The tool is a regular LangChain tool decorated with @tool. The user_id is
patched onto the function object before each graph invocation so the tool
scopes retrieval to the logged-in user's chunks.
"""

from langchain_core.tools import tool

from app.config import settings
from app.db.retrievers import _dense_safe, get_user_bm25_retriever, rerank_texts


@tool
def retrieve_docs(query: str) -> str:
    """Search the user's uploaded documents for relevant information.

    Call this when you need fresh context to answer the user's question.
    Formulate a precise search query that captures the key information needed.
    Returns up to 5 relevant document chunks.
    """
    user_id = getattr(retrieve_docs, "_user_id", None)
    if not user_id:
        return "No documents available (user not set)."

    k = settings.K_RETRIEVE

    # Dense + BM25 in parallel (via to_thread in the caller).
    dense_docs = _dense_safe(query, k=k, user_id=user_id)
    bm25 = get_user_bm25_retriever(user_id, k=k)
    bm25_docs = bm25.invoke(query) if bm25 else []

    pool = list({d.page_content for d in list(dense_docs) + list(bm25_docs)})
    reranked = rerank_texts(query, pool, settings.K_FINAL)

    if not reranked:
        return "No relevant documents found."

    return "\n\n---\n\n".join(
        f"Chunk {i + 1}: {chunk}" for i, chunk in enumerate(reranked)
    )
