from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import settings

llm = ChatOpenAI(
    api_key=settings.FIREWORKS_API_KEY,
    base_url=settings.FIREWORKS_BASE_URL,
    model=settings.FIREWORKS_MODEL_NAME,
    temperature=0,
)

# Vision-capable LLM for scanned/image PDFs + image uploads. Same Fireworks
# base URL (OpenAI-compatible vision endpoint); None when no vision model is
# configured, so callers skip vision extraction entirely.
vision_llm = (
    ChatOpenAI(
        api_key=settings.FIREWORKS_API_KEY,
        base_url=settings.FIREWORKS_BASE_URL,
        model=settings.FIREWORKS_VISION_MODEL_NAME,
        temperature=0,
    )
    if settings.FIREWORKS_VISION_MODEL_NAME
    else None
)

# Dense embeddings via the Fireworks API (OpenAI-compatible embeddings endpoint,
# same base URL + key as the LLM). Replaces the on-device fastembed model.
embeddings = OpenAIEmbeddings(
    api_key=settings.FIREWORKS_API_KEY,
    base_url=settings.FIREWORKS_BASE_URL,
    model=settings.EMBEDDING_MODEL_NAME,
)
