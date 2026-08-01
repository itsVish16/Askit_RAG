"""Fireworks vision extraction for scanned PDFs and image uploads.

A page whose text layer is empty/near-empty (a scanned doc) carries its
content only as an image. We render such pages to PNG with PyMuPDF and send
the image to a Fireworks vision model (OpenAI-compatible) to recover text,
which then flows through the normal chunk + embed + upsert path.

No-op when FIREWORKS_VISION_MODEL_NAME is unset: vision_llm is None and
every function here degrades gracefully (returns "" / skips).
"""

import base64

from langchain_core.messages import HumanMessage
from opik.integrations.langchain import OpikTracer

from app.config import settings
from app.core.llm import vision_llm

# Prompt asks for a faithful text transcription, not an interpretation, so the
# downstream RAG grounds on the page's actual content.
_VISION_PROMPT = (
    "You are an OCR assistant. Transcribe the text in this image verbatim. "
    "Preserve structure (headings, lists, table rows) as plain text. "
    "Output only the transcribed text, no commentary."
)


def is_scanned_page(page, min_chars: int | None = None) -> bool:
    """True if a PyMuPDF page has too little extractable text to be useful."""
    threshold = settings.VISION_MIN_CHARS if min_chars is None else min_chars
    return len(page.get_text().strip()) < threshold


def render_page_png(page, dpi: int | None = None) -> bytes:
    """Render a PyMuPDF page to PNG bytes."""
    pix = page.get_pixmap(dpi=settings.VISION_RENDER_DPI if dpi is None else dpi)
    return pix.tobytes("png")


def extract_text_from_image(img_bytes: bytes, prompt: str = _VISION_PROMPT) -> str:
    """Send one image to the Fireworks vision model, return transcribed text.

    Returns "" on any failure or when no vision model is configured, so callers
    can degrade to whatever text the page already had. Traced via Opik
    (project rule: trace every LLM call).
    """
    if vision_llm is None or not img_bytes:
        return ""
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
    )
    try:
        resp = vision_llm.invoke([msg], config={"callbacks": [OpikTracer()]})
        return resp.content.strip()
    except Exception as exc:
        print(f"  [vision] extraction failed: {type(exc).__name__}: {exc}")
        return ""
