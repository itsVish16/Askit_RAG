"""Builds the worker LangGraph used by the ingest runner.

    fetch_file ──ok──▶ extract_pdf ──ok──▶ chunk ──ok──▶ embed_upsert ──ok──▶ mark_done ─▶ END
        │                  │                │                 │
        └─────────error───┴────────error───┴──────error───────┘
                                  │
                                  ▼
                              mark_done ─▶ END

The 'error' branch fires as soon as any node sets `error_type` ('permanent'
⇒ delete SQS msg; 'transient' ⇒ let visibility timeout redeliver). Retry
policy stays in SQS, not the graph — the single-AWS-service invariant.
"""

from langgraph.graph import END, StateGraph

from app.ingest_worker.nodes import (
    WorkerGraphState,
    chunk_node,
    embed_upsert_node,
    extract_pdf_node,
    fetch_file_node,
    mark_done_node,
    route_after_node,
)

# No checkpointer: SQS owns cross-restart durability (visibility-timeout
# redelivery) and we don't want large pages/chunks arrays in RAM between jobs.
_workflow = StateGraph(WorkerGraphState)
_workflow.add_node("fetch_file", fetch_file_node)
_workflow.add_node("extract_pdf", extract_pdf_node)
_workflow.add_node("chunk", chunk_node)
_workflow.add_node("embed_upsert", embed_upsert_node)
_workflow.add_node("mark_done", mark_done_node)

_workflow.set_entry_point("fetch_file")
_workflow.add_conditional_edges("fetch_file", route_after_node, {"ok": "extract_pdf", "error": "mark_done"})
_workflow.add_conditional_edges("extract_pdf", route_after_node, {"ok": "chunk", "error": "mark_done"})
_workflow.add_conditional_edges("chunk", route_after_node, {"ok": "embed_upsert", "error": "mark_done"})
_workflow.add_conditional_edges("embed_upsert", route_after_node, {"ok": "mark_done", "error": "mark_done"})
_workflow.add_edge("mark_done", END)

worker_agent = _workflow.compile()
