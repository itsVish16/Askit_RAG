import os
from typing import TypedDict

from fastapi import FastAPI
from langgraph.graph import END, StateGraph
from opik.integrations.langchain import OpikTracer
from pydantic import BaseModel

from app.config import settings
from app.core.llm import llm
from app.core.prompts import RAG_PROMPT
from app.db.retrievers import get_hybrid_retriever

os.environ["OPIK_PROJECT_NAME"] = settings.OPIK_PROJECT_NAME


app = FastAPI()


# k=10 (was 3): evals showed context_recall 0.29 — retrieval was
# starved at k=3, so the LLM refused ~half the questions.
retriever = get_hybrid_retriever(k=10)


class UserInput(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str


# graph construction


class GraphState(TypedDict):
    question: str
    context: list[str]
    answer: str


def retrieve_node(state: GraphState):
    print("-- Node: RETRIEVEING CONTEXT --")
    question = state["question"]
    docs = retriever.invoke(question)
    context_list = [doc.page_content for doc in docs]
    return {"context": context_list}


def generate_node(state: GraphState):
    print("-- Node: GENERATING ANSWER --")
    chain = RAG_PROMPT | llm

    response = chain.invoke(
        {"context": "\n\n".join(state["context"]), "question": state["question"]}
    )

    return {"answer": response.content}


workflow = StateGraph(GraphState)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("generate", generate_node)
workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "generate")
workflow.add_edge("generate", END)

app_agent = workflow.compile()


@app.post("/ask", response_model=QueryResponse)
async def ask_query(user_input: UserInput):
    opik_tracer = OpikTracer()

    result = app_agent.invoke(
        {"question": user_input.query}, config={"callbacks": [opik_tracer]}
    )
    return QueryResponse(answer=result["answer"])
