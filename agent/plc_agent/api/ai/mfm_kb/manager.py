# mypy: ignore-errors
"""
KBManager — thread-safe CRUD for MFM Knowledge Base JSON files.

Manages:
- KB entry JSON files in ``agent/data/mfm_kb/``
- Index manifest ``index.json``
- Source PDF storage in ``agent/data/mfm_docs/``
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import IndexEntry, KBEntry, KBIndex

logger = logging.getLogger("loggerfast.ai.mfm_kb.manager")

_DATA_BASE = Path(__file__).resolve().parents[4] / "data"
MFM_DOCS_DIR = _DATA_BASE / "mfm_docs"
MFM_KB_DIR = _DATA_BASE / "mfm_kb"
INDEX_PATH = MFM_KB_DIR / "index.json"


class KBManager:
    """Thread-safe singleton for MFM Knowledge Base operations."""

    _instance: Optional["KBManager"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "KBManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._write_lock = threading.Lock()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        MFM_DOCS_DIR.mkdir(parents=True, exist_ok=True)
        MFM_KB_DIR.mkdir(parents=True, exist_ok=True)

    # -- index management ----------------------------------------------------

    def _load_index(self) -> KBIndex:
        if not INDEX_PATH.exists():
            return KBIndex()
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            return KBIndex.model_validate(data)
        except Exception:
            logger.warning("index_load_failed", exc_info=True)
            return KBIndex()

    def _save_index(self, index: KBIndex) -> None:
        tmp = INDEX_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(index.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(INDEX_PATH)

    # -- public API ----------------------------------------------------------

    def list_models(self) -> list[IndexEntry]:
        index = self._load_index()
        return list(index.models.values())

    def get_entry(self, model: str) -> Optional[KBEntry]:
        key = self._sanitize_model_key(model)
        index = self._load_index()
        idx_entry = index.models.get(key)
        if not idx_entry:
            return None
        path = MFM_KB_DIR / idx_entry.file
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return KBEntry.model_validate(data)
        except Exception:
            logger.warning("entry_load_failed", extra={"model": model}, exc_info=True)
            return None

    @staticmethod
    def validate_entry(entry: KBEntry) -> list[str]:
        """Validate a KB entry for consistency. Returns list of error messages (empty = valid)."""
        errors = []
        seen_params = set()
        for i, reg in enumerate(entry.registers):
            # Duplicate parameter names
            param = reg.parameter if hasattr(reg, "parameter") else reg.get("parameter", "")
            if param in seen_params:
                errors.append(f"Duplicate parameter name: '{param}' (register index {i})")
            seen_params.add(param)

        # Check for overlapping register address ranges
        addr_ranges = []
        for reg in entry.registers:
            addr = reg.address if hasattr(reg, "address") else reg.get("address", 0)
            count = reg.count if hasattr(reg, "count") else reg.get("count", 1)
            param = reg.parameter if hasattr(reg, "parameter") else reg.get("parameter", "")
            addr_ranges.append((addr, addr + count - 1, param))
        addr_ranges.sort()
        for j in range(len(addr_ranges) - 1):
            _, end_a, name_a = addr_ranges[j]
            start_b, _, name_b = addr_ranges[j + 1]
            if end_a >= start_b:
                errors.append(f"Overlapping registers: '{name_a}' (ends at {end_a}) overlaps '{name_b}' (starts at {start_b})")

        return errors

    def save_entry(self, entry: KBEntry) -> str:
        """Save or update a KB entry. Returns the filename."""
        # Validate before saving
        errors = self.validate_entry(entry)
        if errors:
            raise ValueError(f"KB entry validation failed: {'; '.join(errors)}")

        with self._write_lock:
            key = self._sanitize_model_key(entry.model)
            filename = f"{key}.json"
            path = MFM_KB_DIR / filename

            # Auto-increment version if exists
            index = self._load_index()
            existing = index.models.get(key)
            if existing:
                old = self.get_entry(entry.model)
                if old:
                    entry.version = old.version + 1

            # Write entry
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(entry.model_dump(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(path)

            # Update index
            index.models[key] = IndexEntry(
                model=entry.model,
                file=filename,
                version=entry.version,
                source_doc=entry.source_document,
                extraction_date=entry.extraction_date or datetime.now(timezone.utc).isoformat(),
                verified=entry.verified_by_engineer,
            )
            self._save_index(index)

            logger.info("kb_entry_saved", extra={
                "model": entry.model, "key": key,
                "version": entry.version, "registers": len(entry.registers),
            })
            return filename

    def update_entry(self, model: str, patch: dict) -> KBEntry:
        """Partial update of an existing KB entry. Raises KeyError if not found."""
        with self._write_lock:
            key = self._sanitize_model_key(model)
            index = self._load_index()
            if key not in index.models:
                raise KeyError(f"Model '{model}' not found in KB")

            path = MFM_KB_DIR / index.models[key].file
            data = json.loads(path.read_text(encoding="utf-8"))

            # Merge patch
            for k, v in patch.items():
                if k == "registers" and isinstance(v, list):
                    data["registers"] = v
                elif k == "quirks" and isinstance(v, list):
                    data["quirks"] = v
                else:
                    data[k] = v

            # Increment version
            data["version"] = data.get("version", 1) + 1

            entry = KBEntry.model_validate(data)

            # Write back
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(entry.model_dump(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(path)

            # Update index
            index.models[key] = IndexEntry(
                model=entry.model,
                file=index.models[key].file,
                version=entry.version,
                source_doc=entry.source_document,
                extraction_date=entry.extraction_date,
                verified=entry.verified_by_engineer,
            )
            self._save_index(index)
            return entry

    def delete_entry(self, model: str) -> None:
        """Remove a KB entry and its index record. Keeps source PDF."""
        with self._write_lock:
            key = self._sanitize_model_key(model)
            index = self._load_index()
            if key not in index.models:
                raise KeyError(f"Model '{model}' not found in KB")

            # Remove JSON file
            path = MFM_KB_DIR / index.models[key].file
            if path.exists():
                path.unlink()

            # Remove from index
            del index.models[key]
            self._save_index(index)

            logger.info("kb_entry_deleted", extra={"model": model, "key": key})

    def get_source_pdf_path(self, model: str) -> Optional[Path]:
        entry = self.get_entry(model)
        if not entry or not entry.source_document:
            return None
        path = MFM_DOCS_DIR / entry.source_document
        return path if path.exists() else None

    def save_uploaded_pdf(self, filename: str, content: bytes) -> tuple[Path, int]:
        """Save uploaded PDF. Returns (path, page_count)."""
        with self._write_lock:
            safe_name = self._sanitize_filename(filename)
            path = MFM_DOCS_DIR / safe_name
            path.write_bytes(content)

            try:
                import fitz
                doc = fitz.open(str(path))
                page_count = len(doc)
                doc.close()
            except Exception:
                page_count = 0

            logger.info("pdf_uploaded", extra={
                "filename": safe_name, "size": len(content), "pages": page_count,
            })
            return path, page_count

    def list_documents(self) -> list[dict]:
        """List all uploaded PDFs."""
        docs = []
        for f in sorted(MFM_DOCS_DIR.glob("*.pdf")):
            docs.append({"filename": f.name, "size_bytes": f.stat().st_size})
        return docs

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _sanitize_model_key(model: str) -> str:
        s = model.strip().lower()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        return s.strip("_")

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        s = Path(filename).name  # strip directory components
        s = re.sub(r"[^\w.\-]", "_", s)
        if not s.lower().endswith(".pdf"):
            s += ".pdf"
        return s
