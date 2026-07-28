from langchain_core.prompts import ChatPromptTemplate

RAG_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are helpful research assistant."
        "Use ONLY hte following context to answer the question."
        "if the context does not contain the answer,say 'I dont have context to anstwer this question.' \n\n"
        "Context:\n {context}"
    ),
    ("human", "{question}"),
])
 