"""Tests for the ReAct RAG agent workflow (Reasoning + Acting)."""
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.nodes import execute_tools_node, rag_reasoning_node, should_continue_rag
from app.agent.state import GraphState


def test_should_continue_rag_with_tool_call():
    msg = AIMessage(
        content="",
        tool_calls=[{"name": "retrieve_documents", "args": {"query": "covid transmission"}, "id": "call_1"}],
    )
    state: GraphState = {"messages": [msg]}
    assert should_continue_rag(state) == "tools"


def test_should_continue_rag_without_tool_call():
    msg = AIMessage(content="Covid transmits primarily through respiratory droplets.")
    state: GraphState = {"messages": [msg]}
    assert should_continue_rag(state) == "end"


def test_should_continue_rag_empty_messages():
    state: GraphState = {"messages": []}
    assert should_continue_rag(state) == "end"


@pytest.mark.asyncio
async def test_execute_tools_node():
    tool_call = {
        "name": "retrieve_documents",
        "args": {"query": "covid prevention"},
        "id": "tc_123",
    }
    ai_msg = AIMessage(content="", tool_calls=[tool_call])
    state: GraphState = {
        "question": "How to prevent covid?",
        "user_id": "u1",
        "messages": [HumanMessage(content="How to prevent covid?"), ai_msg],
        "context": [],
        "queries": [],
        "keywords": [],
    }

    mock_chunks = ["Wear a mask.", "Wash hands regularly."]
    with patch(
        "app.agent.nodes.retrieve_docs_async",
        new=AsyncMock(return_value=("Chunk 1: Wear a mask.\n\nChunk 2: Wash hands regularly.", ["covid prevention"], ["mask", "hands"], mock_chunks)),
    ):
        result = await execute_tools_node(state)

    assert "messages" in result
    assert len(result["messages"]) == 1
    tool_msg = result["messages"][0]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "tc_123"
    assert "Wear a mask" in tool_msg.content
    assert result["context"] == mock_chunks
    assert result["queries"] == ["covid prevention"]
    assert result["keywords"] == ["mask", "hands"]
    assert result["num_candidates"] == 2
