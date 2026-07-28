# app/ingestion.py
import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter 
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from config import settings

COLLECTION_NAME="askit-documents"
CHUNK_SIZE=500
CHUNK_OVERLAP=50


client = QdrantClient(
    url=settings.QDRANT_URL,
    api_key=settings.QDRANT_API_KEY,
)



def load_parquet_documents(file_path: str, num_rows: int = 50) -> list[Document]:
    print(f"Loading {num_rows} rows from dataset...")
    df = pd.read_parquet(file_path).head(num_rows)
    
    langchain_docs = []
    # Loop over the rows, grab the scientific text arrays, and turn them into LangChain Documents
    for _, row in df.iterrows():
        for doc_text in row["documents"]:
            langchain_docs.append(Document(page_content=doc_text))
            
    # Chunk them exactly like before
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, # Increased slightly for scientific papers
        chunk_overlap=50,
        length_function=len,
        is_separator_regex=False,
    )
    return text_splitter.split_documents(langchain_docs)

def create_and_save_vector_store(chunks: list[Document], save_dir: str = "faiss_index"):
    embeddings = OpenAIEmbeddings(
        model=settings.FIREWORKS_MODEL_NAME_EMBED,
        openai_api_base=settings.FIREWORKS_BASE_URL,
        openai_api_key=settings.FIREWORKS_API_KEY,
    )
    print(f"Embedding {len(chunks)} chunks into FAISS. This may take a minute...")
    vectorstore = QdrantVectorStore.from_documents(chunks, embeddings, url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, collection_name="covidqa_subset")

    print(f"Saved vector store to {save_dir}")
    return vectorstore

if __name__ == "__main__":
    dataset_path = "data/ragbench/covidqa/validation-00000-of-00001.parquet"
    my_chunks = load_parquet_documents(dataset_path, num_rows=50)
    create_and_save_vector_store(my_chunks)
