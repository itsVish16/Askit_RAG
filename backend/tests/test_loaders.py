"""Tests for app/db/loaders.py — file-type loader registry dispatch."""
import pytest

from app.db import loaders
from app.db.loaders import load_document, load_image, load_pdf, load_text, supported_extensions


def test_supported_extensions_registry():
    assert {"pdf", "txt", "md", "png", "jpg", "jpeg"} <= supported_extensions()


def test_load_document_unsupported_extension(tmp_path):
    p = tmp_path / "f.exe"
    p.write_bytes(b"x")
    with pytest.raises(ValueError):
        load_document(str(p), "u1")


def test_load_document_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_document(str(tmp_path / "nope.pdf"), "u1")


def test_load_text_tags_metadata(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hello world")
    docs = load_text(str(p), "u1")
    assert len(docs) == 1
    assert "hello world" in docs[0].page_content
    m = docs[0].metadata
    assert m["user_id"] == "u1"
    assert m["source"] == "text"
    assert m["filename"] == "notes.txt"


def test_load_image_no_vision_returns_empty(monkeypatch):
    monkeypatch.setattr(loaders, "vision_llm", None)
    assert load_image("scan.png", "u1") == []


def test_load_pdf_uses_text_layer(tmp_path, monkeypatch):
    """A text-rich PDF page is extracted via PyMuPDF (extraction='text'), no vision call."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), ("SARS-CoV-2 transmission via respiratory droplets. " * 3))
    p = tmp_path / "doc.pdf"
    doc.save(str(p))
    doc.close()
    docs = load_pdf(str(p), "u1")
    assert len(docs) >= 1
    assert docs[0].metadata["source"] == "pdf"
    assert docs[0].metadata["extraction"] == "text"
    assert docs[0].metadata["filename"] == "doc.pdf"
    assert "SARS-CoV-2" in docs[0].page_content


def test_load_pdf_scanned_page_skipped_without_vision(tmp_path, monkeypatch):
    """A page with no text layer and no vision model is skipped (not crashed)."""
    import fitz

    doc = fitz.open()
    doc.new_page()  # blank page, no text
    p = tmp_path / "blank.pdf"
    doc.save(str(p))
    doc.close()

    monkeypatch.setattr(loaders, "vision_llm", None)
    assert load_pdf(str(p), "u1") == []
