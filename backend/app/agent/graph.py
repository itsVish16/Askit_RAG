from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from app.agent.nodes import generate_node, keyword_node, multi_query_node, retrieve_node
from app.agent.state import GraphState

# multi_query -> keywords -> retrieve -> generate
# In-memory checkpointer keyed by thread_id (= API session_id) gives short-term
# chat memory within a conversation. Lost on restart by design; swap SqliteSaver
# for durable memory.
_workflow = StateGraph(GraphState)
_workflow.add_node("multi_query", multi_query_node)
_workflow.add_node("keywords", keyword_node)
_workflow.add_node("retrieve", retrieve_node)
_workflow.add_node("generate", generate_node)
_workflow.set_entry_point("multi_query")
_workflow.add_edge("multi_query", "keywords")
_workflow.add_edge("keywords", "retrieve")
_workflow.add_edge("retrieve", "generate")
_workflow.add_edge("generate", END)

agent = _workflow.compile(checkpointer=InMemorySaver())
