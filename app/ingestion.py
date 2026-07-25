
import os
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter 
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from config import settings

def load_and_chunk_text(file_path: str) -> list[Document]:
    loader = TextLoader(file_path)
    documents = loader.load()


    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size = 200,
        chunk_overlap = 20,
        length_function = len,
        is_separator_regex = False,
    )

    chunks = text_splitter.split_documents(documents)

    return chunks

def create_and_save_vector_store(chunks: list[Document],save_dir: str = "faiss_index"):
    embeddings  = OpenAIEmbeddings(
        model = settings.FIREWORKS_MODEL_NAME_EMBED,
        openai_api_base = settings.FIREWORKS_BASE_URL,
        openai_api_key = settings.FIREWORKS_API_KEY,
    )

    print(f"Embedding {len(chunks)} chunks")
    vectorstore = FAISS.from_documents(chunks, embeddings)

    vectorstore.save_local(save_dir)
    print(f"Saved vector store to {save_dir}")

    return vectorstore

if __name__ == "__main__":
    test_file = "test_doc.txt"
    with open(test_file, "w") as f:
        f.write("The Eiffel Tower is a wrought-iron lattice tower on the Champ de Mars in Paris, France.\n" * 5)
    my_chunks = load_and_chunk_text(test_file)
    create_and_save_vector_store(my_chunks)

