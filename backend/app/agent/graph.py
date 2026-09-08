from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    chitchat_node,
    execute_tools_node,
    history_node,
    rag_reasoning_node,
    router_node,
    should_continue_rag,
)
from app.agent.state import GraphState


def route_after_router(state: GraphState) -> str:
    """Read the routing decision from the state and branch the graph."""
    decision = state.get("route", "rag")
    if decision in ["chitchat", "history"]:
        return decision
    return "rag"


_workflow = StateGraph(GraphState)

_workflow.add_node("router", router_node)
_workflow.add_node("chitchat", chitchat_node)
_workflow.add_node("history", history_node)
_workflow.add_node("rag", rag_reasoning_node)
_workflow.add_node("tools", execute_tools_node)

_workflow.set_entry_point("router")

_workflow.add_conditional_edges(
    "router",
    route_after_router,
    {
        "rag": "rag",
        "history": "history",
        "chitchat": "chitchat",
    },
)

_workflow.add_conditional_edges(
    "rag",
    should_continue_rag,
    {
        "tools": "tools",
        "end": END,
    },
)

_workflow.add_edge("tools", "rag")
_workflow.add_edge("history", END)
_workflow.add_edge("chitchat", END)

agent = _workflow.compile(checkpointer=InMemorySaver())
