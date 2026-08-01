"""Tests for app/core/vision.py — scanned-page heuristic + vision extraction."""
from app.core import vision
from app.core.vision import extract_text_from_image, is_scanned_page


class FakePage:
    def __init__(self, text: str):
        self._t = text

    def get_text(self):
        return self._t


def test_is_scanned_page_true_for_sparse_text():
    assert is_scanned_page(FakePage("hi")) is True  # < VISION_MIN_CHARS (50)


def test_is_scanned_page_false_for_rich_text():
    assert is_scanned_page(FakePage("x" * 100)) is False


def test_extract_returns_empty_when_no_vision_model(monkeypatch):
    monkeypatch.setattr(vision, "vision_llm", None)
    assert extract_text_from_image(b"pngbytes") == ""


def test_extract_invokes_vision_llm(monkeypatch):
    class FakeResp:
        content = "transcribed text"

    class FakeLLM:
        def invoke(self, msgs, config=None):
            return FakeResp()

    monkeypatch.setattr(vision, "vision_llm", FakeLLM())
    monkeypatch.setattr(vision, "OpikTracer", lambda *a, **k: None)  # no Opik in unit tests
    assert extract_text_from_image(b"pngbytes") == "transcribed text"


def test_extract_returns_empty_on_llm_failure(monkeypatch):
    class BoomLLM:
        def invoke(self, msgs, config=None):
            raise RuntimeError("vision api down")

    monkeypatch.setattr(vision, "vision_llm", BoomLLM())
    monkeypatch.setattr(vision, "OpikTracer", lambda *a, **k: None)
    assert extract_text_from_image(b"pngbytes") == ""
