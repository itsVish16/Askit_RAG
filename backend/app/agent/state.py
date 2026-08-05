from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class GraphState(TypedDict, total=False):
    question: str
    queries: list[str]  # original + LLM-expanded variants
    keywords: list[str]  # extracted domain terms for BM25
    context: list[str]
    num_candidates: int
    answer: str
    user_id: str | None  # per-user PDF scope; None = shared corpus
    route: str  # fast-path routing decision (e.g. 'rag' vs 'chitchat')
    # Short-term conversation memory. add_messages appends (not overwrites)
    # so prior turns survive across /ask calls in the same thread_id.
    chat_history: Annotated[list[BaseMessage], add_messages]
