"""File-type loader registry for ingestion.

Dispatches by extension to the right loader, tags each Document with the
metadata contract the retriever layer depends on (metadata.user_id for
per-user scoping, metadata.source / filename / page for provenance).

  pdf  -> PyMuPDF text extraction, with a vision-model fallback per page when
          the text layer is sparse (scanned docs) and a vision model is set.
  txt/md -> TextLoader (one Document per file).
  png/jpg/jpeg -> vision model direct (one Document per image).

Add a type by registering a loader in LOADERS below.
"""

import os
from collections.abc import Callable

import fitz  # PyMuPDF
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document

from app.core.llm import vision_llm
from app.core.vision import extract_text_from_image, is_scanned_page, render_page_png


def _tag(metadata: dict, user_id: str, source: str, filename: str) -> dict:
    return {**metadata, "user_id": user_id, "source": source, "filename": filename}


def load_pdf(file_path: str, user_id: str) -> list[Document]:
    """Load a PDF with PyMuPDF. Per page: use the text layer when it's rich;
    otherwise render to PNG and call the vision model (if configured). Pages
    with no text AND no vision recovery are skipped."""
    filename = os.path.basename(file_path)
    docs: list[Document] = []
    with fitz.open(file_path) as doc:
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            extraction = "text"
            if is_scanned_page(page) and len(text) == 0:
                # No text layer at all — try vision if available.
                if vision_llm is not None:
                    text = extract_text_from_image(render_page_png(page))
                    extraction = "vision"
                else:
                    continue  # nothing to embed
            elif is_scanned_page(page) and vision_llm is not None:
                # Sparse text: augment with vision so figures/captions aren't lost.
                vision_text = extract_text_from_image(render_page_png(page))
                if vision_text:
                    text = f"{text}\n{vision_text}" if text else vision_text
                    extraction = "text+vision"
            if not text:
                continue
            docs.append(
                Document(
                    page_content=text,
                    metadata=_tag({"page": i + 1}, user_id, "pdf", filename) | {"extraction": extraction},
                )
            )
    print(f"Loaded {len(docs)} pages from {filename} (user_id={user_id})")
    return docs


def load_text(file_path: str, user_id: str) -> list[Document]:
    """TXT/MD via LangChain TextLoader, tagged with user scope + provenance."""
    filename = os.path.basename(file_path)
    raw = TextLoader(file_path).load()
    docs = [
        Document(page_content=d.page_content, metadata=_tag(d.metadata, user_id, "text", filename))
        for d in raw
    ]
    print(f"Loaded {len(docs)} text section(s) from {filename} (user_id={user_id})")
    return docs


def load_image(file_path: str, user_id: str) -> list[Document]:
    """Image file -> one Document whose content is the vision transcription."""
    if vision_llm is None:
        print(f"  [loaders] image upload {file_path} skipped (no vision model configured)")
        return []
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as buf:
        text = extract_text_from_image(buf.read())
    if not text:
        return []
    print(f"Loaded 1 image {filename} via vision (user_id={user_id})")
    return [Document(page_content=text, metadata=_tag({"page": 1}, user_id, "image", filename))]


LOADERS: dict[str, Callable[[str, str], list[Document]]] = {
    "pdf": load_pdf,
    "txt": load_text,
    "md": load_text,
    "png": load_image,
    "jpg": load_image,
    "jpeg": load_image,
}


def supported_extensions() -> set[str]:
    return set(LOADERS)


def load_document(file_path: str, user_id: str) -> list[Document]:
    """Dispatch to the right loader by file extension. Raises ValueError on
    an unsupported type (the API layer converts that into HTTP 400)."""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    loader = LOADERS.get(ext)
    if loader is None:
        raise ValueError(
            f"Unsupported file extension '.{ext}'. Supported: {sorted(LOADERS)}."
        )
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)
    return loader(file_path, user_id)
