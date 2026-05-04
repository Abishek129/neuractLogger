# mypy: ignore-errors
"""
KB Router — FastAPI endpoints for the MFM Knowledge Base.

Endpoints (nested under /ai/kb via router.include_router):
    GET    /ai/kb                           — list all models
    GET    /ai/kb/{model}                   — get full KB entry
    POST   /ai/kb/upload                    — upload PDF for ingestion
    POST   /ai/kb/{model}                   — create or update KB entry
    DELETE /ai/kb/{model}                   — remove KB entry
    GET    /ai/kb/{model}/document          — download source PDF
    GET    /ai/kb/{model}/document/page/{p} — render PDF page as PNG
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response

from .manager import KBManager
from .models import (
    KBCreateUpdateRequest,
    KBCreateUpdateResponse,
    KBDeleteResponse,
    KBEntryResponse,
    KBListItem,
    KBListResponse,
    KBUploadResponse,
)

logger = logging.getLogger("loggerfast.ai.mfm_kb.router")

kb_router = APIRouter(prefix="/kb", tags=["ai-kb"])

_MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@kb_router.get("", response_model=KBListResponse)
def list_kb_models():
    """List all models in the knowledge base."""
    mgr = KBManager.instance()
    models = mgr.list_models()
    items = []
    for m in models:
        entry = mgr.get_entry(m.model)
        items.append(KBListItem(
            model=m.model,
            manufacturer=entry.manufacturer if entry else "",
            protocol=entry.protocol if entry else "",
            register_count=len(entry.registers) if entry else 0,
            verified=m.verified,
        ))
    return KBListResponse(models=items, count=len(items))


@kb_router.get("/{model}", response_model=KBEntryResponse)
def get_kb_entry(model: str):
    """Get full KB entry for a model."""
    mgr = KBManager.instance()
    entry = mgr.get_entry(model)
    if not entry:
        raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")

    warnings = []
    if not entry.verified_by_engineer:
        warnings.append(
            "This entry is UNVERIFIED (auto-extracted). "
            "Engineer verification recommended before production use."
        )
    return KBEntryResponse(entry=entry, warnings=warnings)


@kb_router.post("/upload", response_model=KBUploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """Upload a manufacturer communication guide PDF for ingestion."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF_REQUIRED")

    content = await file.read()
    if len(content) > _MAX_PDF_SIZE:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="EMPTY_FILE")

    mgr = KBManager.instance()
    path, pages = mgr.save_uploaded_pdf(file.filename, content)

    return KBUploadResponse(
        filename=path.name,
        size_bytes=len(content),
        pages=pages,
        message=f"Uploaded {path.name} ({pages} pages). Use read_document or read_document_page_image to extract register maps.",
    )


@kb_router.post("/{model}", response_model=KBCreateUpdateResponse)
def create_or_update_entry(model: str, body: KBCreateUpdateRequest):
    """Create or update a KB entry."""
    entry = body.entry
    entry.model = model  # ensure path param matches

    mgr = KBManager.instance()
    filename = mgr.save_entry(entry)

    return KBCreateUpdateResponse(
        model=entry.model,
        version=entry.version,
        file=filename,
        message=f"KB entry for {entry.model} saved (v{entry.version}).",
    )


@kb_router.delete("/{model}", response_model=KBDeleteResponse)
def delete_entry(model: str):
    """Remove a KB entry (keeps source PDF)."""
    mgr = KBManager.instance()
    try:
        mgr.delete_entry(model)
    except KeyError:
        raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")

    return KBDeleteResponse(model=model, message=f"KB entry for '{model}' deleted.")


@kb_router.get("/{model}/document")
def download_source_pdf(model: str):
    """Download the source PDF for a model."""
    mgr = KBManager.instance()
    pdf_path = mgr.get_source_pdf_path(model)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="SOURCE_PDF_NOT_FOUND")

    return Response(
        content=pdf_path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{pdf_path.name}"'},
    )


@kb_router.get("/{model}/document/page/{page}")
def render_document_page(model: str, page: int):
    """Render a specific PDF page as PNG. Page is 1-indexed."""
    if page < 1:
        raise HTTPException(status_code=400, detail="PAGE_MUST_BE_POSITIVE")

    mgr = KBManager.instance()
    pdf_path = mgr.get_source_pdf_path(model)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="SOURCE_PDF_NOT_FOUND")

    from .ocr import render_pdf_page, get_pdf_page_count

    total = get_pdf_page_count(pdf_path)
    if page > total:
        raise HTTPException(status_code=400, detail=f"PAGE_OUT_OF_RANGE (max {total})")

    png_bytes = render_pdf_page(pdf_path, page - 1, dpi=200)  # 200 DPI for preview

    return Response(
        content=png_bytes,
        media_type="image/png",
    )
