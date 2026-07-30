from langchain_core.prompts import ChatPromptTemplate

RAG_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            ("You are a helpful research assistant. "
            "Use ONLY the following context to answer the question. "
            "If the context does not contain the answer, say "
            "'I don't have context to answer this question.'\n\n"
            "Context:\n{context}"),
        ),
        ("human", "{question}"),
    ]
)
