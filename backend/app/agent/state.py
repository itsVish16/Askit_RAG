from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class GraphState(TypedDict, total=False):
    question: str
    queries: list[str]
    keywords: list[str]
    context: list[str]
    num_candidates: int
    answer: str
    user_id: str | None
    corpus_scope: str  # "user" (default) or "shared" (for evals)
    route: str
    chat_history: Annotated[list[BaseMessage], add_messages]
