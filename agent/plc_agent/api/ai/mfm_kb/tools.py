# mypy: ignore-errors
"""
MFM Knowledge Base tools for the Hermes agent.

8 tools:
  Read:  lookup_mfm_model, list_mfm_models, read_document,
         read_document_page_image, read_mfm_document, search_mfm_document
  Write: propose_kb_entry, update_kb_entry
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

logger = logging.getLogger("loggerfast.ai.mfm_kb.tools")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_pages(pages_str: str, total: int) -> list[int]:
    """Parse user page spec ('1,3,5' or '1-5') into 0-indexed list."""
    result = set()
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            for p in range(int(lo), int(hi) + 1):
                if 1 <= p <= total:
                    result.add(p - 1)
        else:
            p = int(part)
            if 1 <= p <= total:
                result.add(p - 1)
    return sorted(result)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def lookup_mfm_model(ctx, *, model: str, **kwargs) -> dict:
    """Get full register map for a device model from the MFM KB."""
    from .manager import KBManager

    mgr = KBManager.instance()
    entry = mgr.get_entry(model)
    if not entry:
        return {"error": "model_not_found", "model": model,
                "message": f"Model '{model}' not found in knowledge base."}

    result = entry.model_dump()
    result["register_count"] = len(entry.registers)
    if not entry.verified_by_engineer:
        result["warning"] = (
            "This entry is UNVERIFIED (auto-extracted). "
            "Engineer verification recommended before production use."
        )
    return result


async def list_mfm_models(ctx, **kwargs) -> dict:
    """List all models in the MFM knowledge base."""
    from .manager import KBManager

    mgr = KBManager.instance()
    models = mgr.list_models()
    items = []
    for m in models:
        entry = mgr.get_entry(m.model)
        items.append({
            "model": m.model,
            "manufacturer": entry.manufacturer if entry else "",
            "protocol": entry.protocol if entry else "",
            "register_count": len(entry.registers) if entry else 0,
            "verified": m.verified,
            "version": m.version,
        })
    return {"models": items, "count": len(items)}


async def read_document(ctx, *, path: str, pages: str = "", **kwargs) -> dict:
    """Extract text from a PDF. Native extraction + GLM-OCR fallback."""
    from .manager import MFM_DOCS_DIR
    from .ocr import extract_text_native, get_pdf_page_count, ocr_pdf_page

    pdf_path = MFM_DOCS_DIR / path
    if not pdf_path.exists():
        return {"error": "pdf_not_found", "path": path,
                "message": f"PDF '{path}' not found in documents folder."}

    total = get_pdf_page_count(pdf_path)
    target_pages = _parse_pages(pages, total) if pages else list(range(total))

    # Cap at 10 pages to avoid context overflow
    if len(target_pages) > 10:
        target_pages = target_pages[:10]
        capped = True
    else:
        capped = False

    # Try native text extraction first
    text = extract_text_native(pdf_path, target_pages)
    used_ocr = False

    # If native extraction yields very little, fall back to OCR for each page
    if len(text.strip()) < 100 and len(target_pages) <= 3:
        ocr_parts = []
        for p in target_pages:
            try:
                ocr_text = ocr_pdf_page(pdf_path, p)
                if ocr_text:
                    ocr_parts.append(f"--- Page {p + 1} (OCR) ---\n{ocr_text}")
            except Exception as e:
                ocr_parts.append(f"--- Page {p + 1} (OCR failed: {e}) ---")
        if ocr_parts:
            text = "\n\n".join(ocr_parts)
            used_ocr = True

    return {
        "path": path,
        "total_pages": total,
        "pages_extracted": [p + 1 for p in target_pages],
        "used_ocr": used_ocr,
        "capped_at_10": capped,
        "text": text[:15000],  # cap text to avoid context overflow
        "text_length": len(text),
    }


async def read_document_page_image(ctx, *, path: str, page: int, **kwargs) -> dict:
    """Render a PDF page at 400 DPI and run GLM-OCR on it."""
    from .manager import MFM_DOCS_DIR
    from .ocr import get_pdf_page_count, ocr_pdf_page

    pdf_path = MFM_DOCS_DIR / path
    if not pdf_path.exists():
        return {"error": "pdf_not_found", "path": path,
                "message": f"PDF '{path}' not found in documents folder."}

    total = get_pdf_page_count(pdf_path)
    page_0 = page - 1  # convert to 0-indexed
    if page_0 < 0 or page_0 >= total:
        return {"error": "page_out_of_range", "page": page, "total_pages": total}

    try:
        text = ocr_pdf_page(
            pdf_path, page_0,
            prompt=(
                "Extract all text, tables, and data from this page. "
                "Pay special attention to register map tables. "
                "For each table row, extract: register address, "
                "parameter name, data type, unit, and access mode."
            ),
        )
    except RuntimeError as e:
        return {"error": "vision_not_enabled", "message": str(e)}
    except Exception as e:
        return {"error": "ocr_failed", "message": str(e)}

    return {
        "path": path,
        "page": page,
        "total_pages": total,
        "text": text[:15000],
        "text_length": len(text),
    }


async def propose_kb_entry(ctx, *, model: str, data: dict, **kwargs) -> dict:
    """Create a DRAFT KB entry. Always sets verified_by_engineer=False."""
    from .manager import KBManager
    from .models import KBEntry

    data["model"] = model
    data["verified_by_engineer"] = False  # write gate
    data["extraction_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        entry = KBEntry.model_validate(data)
    except Exception as e:
        return {"error": "validation_failed", "message": str(e)}

    mgr = KBManager.instance()
    filename = mgr.save_entry(entry)

    return {
        "model": entry.model,
        "file": filename,
        "version": entry.version,
        "register_count": len(entry.registers),
        "verified_by_engineer": False,
        "message": (
            f"KB entry for {entry.manufacturer} {entry.model} saved as DRAFT. "
            f"{len(entry.registers)} registers. "
            "Engineer verification required before production use."
        ),
    }


async def update_kb_entry(ctx, *, model: str, patch: dict, **kwargs) -> dict:
    """Patch an existing KB entry. Resets verification to draft."""
    from .manager import KBManager

    patch["verified_by_engineer"] = False  # write gate

    mgr = KBManager.instance()
    try:
        entry = mgr.update_entry(model, patch)
    except KeyError:
        return {"error": "model_not_found", "model": model,
                "message": f"Model '{model}' not found in KB."}
    except Exception as e:
        return {"error": "update_failed", "message": str(e)}

    return {
        "model": entry.model,
        "version": entry.version,
        "register_count": len(entry.registers),
        "verified_by_engineer": False,
        "message": f"KB entry for {entry.model} updated to v{entry.version} (DRAFT).",
    }


async def read_mfm_document(ctx, *, model: str, page: int, **kwargs) -> dict:
    """Read a specific page from a model's source PDF."""
    from .manager import KBManager
    from .ocr import extract_text_native, get_pdf_page_count

    mgr = KBManager.instance()
    pdf_path = mgr.get_source_pdf_path(model)
    if not pdf_path:
        return {"error": "pdf_not_found", "model": model,
                "message": f"No source PDF found for model '{model}'."}

    total = get_pdf_page_count(pdf_path)
    page_0 = page - 1
    if page_0 < 0 or page_0 >= total:
        return {"error": "page_out_of_range", "page": page, "total_pages": total}

    text = extract_text_native(pdf_path, [page_0])
    return {
        "model": model,
        "page": page,
        "total_pages": total,
        "source_document": pdf_path.name,
        "text": text[:15000],
        "text_length": len(text),
    }


async def search_mfm_document(ctx, *, model: str, query: str, **kwargs) -> dict:
    """Search a model's source PDF by keyword."""
    from .manager import KBManager
    from .ocr import search_pdf_text

    mgr = KBManager.instance()
    pdf_path = mgr.get_source_pdf_path(model)
    if not pdf_path:
        return {"error": "pdf_not_found", "model": model,
                "message": f"No source PDF found for model '{model}'."}

    results = search_pdf_text(pdf_path, query)
    return {
        "model": model,
        "query": query,
        "source_document": pdf_path.name,
        "results": results,
        "match_count": sum(r["match_count"] for r in results),
        "pages_matched": len(results),
    }


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

MFM_KB_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_mfm_model",
            "description": "Get the full register map for a device model from the MFM knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Model name (e.g. PM5110, B24, MFM376)"},
                },
                "required": ["model"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_mfm_models",
            "description": "List all device models in the MFM knowledge base with manufacturer, register count, and verification status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "Extract text from a manufacturer PDF datasheet. Uses native text extraction with GLM-OCR fallback for scanned pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "PDF filename in the documents folder."},
                    "pages": {"type": "string", "description": "Page numbers: '1,3,5' or '1-5' (1-indexed). Omit for all pages."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document_page_image",
            "description": "Render a PDF page at 400 DPI and run GLM-OCR for structured table extraction. Best for register map tables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "PDF filename in the documents folder."},
                    "page": {"type": "integer", "description": "Page number (1-indexed)."},
                },
                "required": ["path", "page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_kb_entry",
            "description": "Create a DRAFT KB entry from extracted register map data. Entry is saved as unverified — engineer must verify before production use.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Model name."},
                    "data": {"type": "object", "description": "KB entry data: manufacturer, protocol, byte_order, registers[], quirks[], source_document."},
                },
                "required": ["model", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_kb_entry",
            "description": "Update an existing KB entry with corrections or additions. Resets verification status to draft.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Model name."},
                    "patch": {"type": "object", "description": "Fields to update (partial)."},
                },
                "required": ["model", "patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_mfm_document",
            "description": "Read a specific page from a model's source PDF for verification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Model name."},
                    "page": {"type": "integer", "description": "Page number (1-indexed)."},
                },
                "required": ["model", "page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_mfm_document",
            "description": "Search a model's source PDF by keyword (e.g. 'byte order', 'energy counter', 'unit ID').",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Model name."},
                    "query": {"type": "string", "description": "Search keyword or phrase."},
                },
                "required": ["model", "query"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

MFM_KB_TOOL_DISPATCH: Dict[str, Callable] = {
    "lookup_mfm_model": lookup_mfm_model,
    "list_mfm_models": list_mfm_models,
    "read_document": read_document,
    "read_document_page_image": read_document_page_image,
    "propose_kb_entry": propose_kb_entry,
    "update_kb_entry": update_kb_entry,
    "read_mfm_document": read_mfm_document,
    "search_mfm_document": search_mfm_document,
}
