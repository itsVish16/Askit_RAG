from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import settings

llm = ChatOpenAI(
    api_key=settings.FIREWORKS_API_KEY,
    base_url=settings.FIREWORKS_BASE_URL,
    model=settings.FIREWORKS_MODEL_NAME,
)

embeddings = OpenAIEmbeddings(
    api_key=settings.FIREWORKS_API_KEY,
    base_url=settings.FIREWORKS_BASE_URL,
    model=settings.FIREWORKS_MODEL_NAME_EMBED,
)
