# mypy: ignore-errors
"""
OCR module — GLM-OCR integration + PDF processing for register map extraction.

Uses:
- PyMuPDF (fitz) for PDF page rendering at 400 DPI
- GLM-OCR via Ollama native API for text/table extraction from images
- httpx for HTTP calls to Ollama
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("loggerfast.ai.mfm_kb.ocr")


# ---------------------------------------------------------------------------
# PDF operations (PyMuPDF)
# ---------------------------------------------------------------------------

def render_pdf_page(pdf_path: Path, page_num: int, dpi: int = 400) -> bytes:
    """Render a single PDF page as PNG bytes.

    Args:
        pdf_path: Path to PDF file.
        page_num: 0-indexed page number.
        dpi: Resolution (400 for OCR quality).

    Returns:
        PNG image bytes.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        if page_num < 0 or page_num >= len(doc):
            raise IndexError(f"Page {page_num} out of range (0-{len(doc) - 1})")
        pix = doc[page_num].get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def get_pdf_page_count(pdf_path: Path) -> int:
    """Return total page count for a PDF."""
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


def extract_text_native(pdf_path: Path, pages: Optional[list[int]] = None) -> str:
    """Extract text from PDF using PyMuPDF's native text extraction.

    Args:
        pdf_path: Path to PDF.
        pages: 0-indexed page numbers. None = all pages.

    Returns:
        Concatenated text from requested pages.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        result_parts = []
        target_pages = pages if pages is not None else range(len(doc))
        for i in target_pages:
            if 0 <= i < len(doc):
                text = doc[i].get_text()
                if text.strip():
                    result_parts.append(f"--- Page {i + 1} ---\n{text}")
        return "\n\n".join(result_parts)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# GLM-OCR via Ollama
# ---------------------------------------------------------------------------

def ocr_image(
    png_bytes: bytes,
    prompt: str = "Extract all text from this image.",
    timeout: float = 180.0,
) -> str:
    """Send a PNG image to GLM-OCR via Ollama and return extracted text.

    Uses LLMConfig.vision_* fields for endpoint configuration.

    Raises:
        RuntimeError: Vision model not enabled or API call failed.
    """
    import httpx
    from ..llm import get_llm_config

    config = get_llm_config()
    if not config.vision_enabled or not config.vision_model:
        raise RuntimeError(
            "Vision model (GLM-OCR) not enabled. "
            "Set VISION_AI_ENABLED=true, VISION_AI_MODEL=glm-ocr"
        )

    # Ollama native API — strip /v1 suffix
    api_base = (config.vision_api_base or "http://localhost:11434/v1").rstrip("/")
    if api_base.endswith("/v1"):
        api_base = api_base[:-3]

    b64_image = base64.b64encode(png_bytes).decode("ascii")

    logger.info("ocr_request", extra={
        "model": config.vision_model,
        "image_size": len(png_bytes),
        "prompt_len": len(prompt),
    })

    resp = httpx.post(
        f"{api_base}/api/generate",
        json={
            "model": config.vision_model,
            "prompt": prompt,
            "images": [b64_image],
            "stream": False,
            "options": {"num_predict": 4096, "temperature": 0},
        },
        timeout=timeout,
    )
    resp.raise_for_status()

    text = resp.json().get("response", "")
    # Strip markdown bold markers some models add
    text = text.replace("**", "")

    logger.info("ocr_result", extra={
        "model": config.vision_model,
        "chars": len(text),
    })
    return text.strip()


def ocr_pdf_page(
    pdf_path: Path,
    page_num: int,
    prompt: str = "Extract all text, tables, and register maps from this page.",
) -> str:
    """Render a PDF page and run OCR on it. Convenience wrapper."""
    png_bytes = render_pdf_page(pdf_path, page_num, dpi=400)
    return ocr_image(png_bytes, prompt=prompt)


# ---------------------------------------------------------------------------
# PDF search
# ---------------------------------------------------------------------------

def search_pdf_text(pdf_path: Path, query: str) -> list[dict]:
    """Search PDF for keyword matches across all pages.

    Uses native text extraction. Returns list of
    ``{page: int, matches: list[str], context: str}`` dicts.
    Page numbers are 1-indexed in output.
    """
    import fitz

    query_lower = query.lower()
    results = []

    doc = fitz.open(str(pdf_path))
    try:
        for i in range(len(doc)):
            text = doc[i].get_text()
            if query_lower not in text.lower():
                continue

            # Extract matching lines with context
            lines = text.splitlines()
            matches = []
            for j, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(0, j - 1)
                    end = min(len(lines), j + 2)
                    context = "\n".join(lines[start:end])
                    matches.append(context)

            if matches:
                results.append({
                    "page": i + 1,  # 1-indexed for user
                    "match_count": len(matches),
                    "matches": matches[:5],  # cap at 5 per page
                })
    finally:
        doc.close()

    return results
