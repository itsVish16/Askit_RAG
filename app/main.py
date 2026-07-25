from fastapi import FastAPI
from typing import TypedDict, List
from pydantic import BaseModel
from openai import OpenAI
from app.config import settings
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from app.config import settings
import os
import opik
from opik.integrations.langchain import OpikTracer

os.environ["OPIK_PROJECT_NAME"] = settings.OPIK_PROJECT_NAME

app = FastAPI()

class UserInput(BaseModel):
    query: str

class QueryResponse(BaseModel):
    answer: str

llm = ChatOpenAI(
    base_url=settings.FIREWORKS_BASE_URL,
    api_key=settings.FIREWORKS_API_KEY,
    model = settings.FIREWORKS_MODEL_NAME,
)



embeddings  = OpenAIEmbeddings(
    model = settings.FIREWORKS_MODEL_NAME_EMBED,
    openai_api_base = settings.FIREWORKS_BASE_URL,
    openai_api_key = settings.FIREWORKS_API_KEY,
)

vectorstore = FAISS.load_local(
    "faiss_index",
    embeddings,
    allow_dangerous_deserialization=True
)

retriever = vectorstore.as_retriever(search_kwargs = {"k":3})


#graph construction

class GraphState(TypedDict):
    question: str
    context: list[str]
    answer: str


def retrieve_node(state: GraphState):
    print("-- Node: RETRIEVEING CONTEXT --")
    question = state["question"]


    docs = retriever.invoke(question)

    context_list = [doc.page_content for  doc in docs]

    return {"context":context_list}

def generate_node(state: GraphState):
    print("-- Node: GENERATING ANSWER --")
    question = state["question"]
    context = state["context"]

    prompt = ChatPromptTemplate.from_messages([
        ("system", "your are an assistant. Use the following context to answer the question: \n\n{context}"),
        ("human", "{question}"),
    ])

    chain  = prompt | llm

    response = chain.invoke({"context" : "\n\n".join(context), "question": question})

    return {"answer":response.content}

workflow = StateGraph(GraphState)

workflow.add_node("retrieve", retrieve_node)
workflow.add_node("generate", generate_node)

workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "generate")
workflow.add_edge("generate", END)

app_agent = workflow.compile()


@app.post("/ask", response_model = QueryResponse)
def ask_query(user_input: UserInput):
    initial_state  = {"question":user_input.query}
    opik_tracer = OpikTracer()
    result = app_agent.invoke(initial_state, config = {"callbacks": [opik_tracer]})


    return QueryResponse(answer = result["answer"])
