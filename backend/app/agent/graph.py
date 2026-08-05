from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from app.agent.nodes import chitchat_node, rag_agent_node, router_node
from app.agent.state import GraphState


def route_after_router(state: GraphState) -> str:
    """Read the routing decision from the state and branch the graph."""
    decision = state.get("route", "rag")
    if decision == "chitchat":
        return "chitchat"
    return "rag"


_workflow = StateGraph(GraphState)

_workflow.add_node("router", router_node)
_workflow.add_node("chitchat", chitchat_node)
_workflow.add_node("rag", rag_agent_node)

_workflow.set_entry_point("router")

_workflow.add_conditional_edges(
    "router",
    route_after_router,
    {
        "rag": "rag",
        "chitchat": "chitchat",
    },
)

_workflow.add_edge("rag", END)
_workflow.add_edge("chitchat", END)

agent = _workflow.compile(checkpointer=InMemorySaver())
