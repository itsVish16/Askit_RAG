from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_openai import ChatOpenAI

from app.config import settings

llm = ChatOpenAI(
    api_key=settings.FIREWORKS_API_KEY,
    base_url=settings.FIREWORKS_BASE_URL,
    model=settings.FIREWORKS_MODEL_NAME,
)

# Local dense embeddings via fastembed — replaced the Fireworks embeddings
# whose dense-only recall was 0.096 (BM25 beat them 3.4x). bge-large: 1024-dim,
# English-only and production-proven; COVID-QA is English. Auto-quantized on CPU.
embeddings = FastEmbedEmbeddings(model_name=settings.EMBEDDING_MODEL_NAME)
