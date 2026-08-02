from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from app.agent.nodes import react_agent_node
from app.agent.state import GraphState

# Single-agent graph:
#
#   react_agent_node (LLM + retrieve_docs tool)
#     ├─ answers directly from history/context → END  (~4s)
#     └─ calls retrieve_docs → gets context → answers → END  (~8-15s)
#
# Tool calls are handled inside the agent node via a ReAct loop (up to 3
# turns). No separate ToolNode or conditional edges needed.
#
# In-memory checkpointer keyed by thread_id (= API session_id) gives short-term
# chat memory within a conversation. Lost on restart by design.

_workflow = StateGraph(GraphState)
_workflow.add_node("agent", react_agent_node)
_workflow.set_entry_point("agent")
_workflow.add_edge("agent", END)

agent = _workflow.compile(checkpointer=InMemorySaver())
