# mypy: ignore-errors
"""Phase 3D — Skill Marketplace: versioned, rated, cross-deployment skill repository."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("loggerfast.ai.marketplace")

# Storage directory — alongside other AI data
_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "skill_marketplace"


@dataclass
class MarketplaceEntry:
    """A versioned, rated skill in the marketplace."""
    skill_id: str
    skill_name: str
    description: str
    version: int
    tags: list[str]
    success_count: int = 0
    failure_count: int = 0
    author_deployment: str = ""
    content_hash: str = ""
    deprecated: bool = False
    created_at: str = ""
    updated_at: str = ""

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 3),
            "author_deployment": self.author_deployment,
            "content_hash": self.content_hash,
            "deprecated": self.deprecated,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SkillMarketplace:
    """Manages a versioned, rated skill repository with cross-deployment support."""

    _instance: Optional["SkillMarketplace"] = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[str, MarketplaceEntry] = {}  # skill_id -> entry
        self._name_index: Dict[str, list[str]] = {}      # skill_name -> [skill_ids] by version
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    @classmethod
    def instance(cls) -> "SkillMarketplace":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = SkillMarketplace()
            return cls._instance

    # ------------------------------------------------------------------
    # Publish / Update
    # ------------------------------------------------------------------

    def publish(self, skill_name: str, content: Dict[str, Any]) -> MarketplaceEntry:
        """Publish or update a skill. Auto-increments version if content changed."""
        content_hash = _hash_content(content)
        now = _now()

        with self._lock:
            existing = self._name_index.get(skill_name, [])

            # Check for duplicate content
            for sid in existing:
                if self._entries[sid].content_hash == content_hash:
                    return self._entries[sid]  # already exists, skip

            # New version
            version = len(existing) + 1
            skill_id = uuid.uuid4().hex[:12]
            entry = MarketplaceEntry(
                skill_id=skill_id,
                skill_name=skill_name,
                description=content.get("description", ""),
                version=version,
                tags=content.get("tags", []),
                author_deployment=content.get("author_deployment", _deployment_id()),
                content_hash=content_hash,
                created_at=now,
                updated_at=now,
            )
            self._entries[skill_id] = entry
            self._name_index.setdefault(skill_name, []).append(skill_id)
            self._save_entry(entry, content)

        logger.info("marketplace_publish name=%s v%d id=%s", skill_name, version, skill_id)
        return entry

    # ------------------------------------------------------------------
    # Search / Query
    # ------------------------------------------------------------------

    def search(
        self,
        query: str = "",
        tags: Optional[List[str]] = None,
        min_rating: float = 0.0,
        limit: int = 20,
    ) -> List[MarketplaceEntry]:
        """Search marketplace with filters."""
        with self._lock:
            results = []
            for entry in self._entries.values():
                if entry.deprecated:
                    continue
                if min_rating > 0 and entry.success_rate < min_rating:
                    continue
                if tags and not set(tags).intersection(entry.tags):
                    continue
                if query:
                    q = query.lower()
                    if (q not in entry.skill_name.lower()
                            and q not in entry.description.lower()
                            and not any(q in t.lower() for t in entry.tags)):
                        continue
                results.append(entry)
            # Sort by success rate descending, then version descending
            results.sort(key=lambda e: (e.success_rate, e.version), reverse=True)
            return results[:limit]

    def get_entry(self, skill_id: str) -> Optional[MarketplaceEntry]:
        with self._lock:
            return self._entries.get(skill_id)

    def get_latest(self, skill_name: str) -> Optional[MarketplaceEntry]:
        """Get the latest version of a skill by name."""
        with self._lock:
            ids = self._name_index.get(skill_name, [])
            if not ids:
                return None
            return self._entries[ids[-1]]

    def get_top_skills(self, n: int = 10) -> List[MarketplaceEntry]:
        """Get highest-rated non-deprecated skills."""
        return self.search(limit=n)

    # ------------------------------------------------------------------
    # Rating / Outcome
    # ------------------------------------------------------------------

    def record_outcome(self, skill_name: str, success: bool) -> None:
        """Record usage outcome on the latest version of a skill."""
        with self._lock:
            ids = self._name_index.get(skill_name, [])
            if not ids:
                return
            entry = self._entries[ids[-1]]
            if success:
                entry.success_count += 1
            else:
                entry.failure_count += 1
            entry.updated_at = _now()
            self._persist_index()

    def deprecate(self, skill_name: str, version: Optional[int] = None) -> bool:
        """Mark a skill version as deprecated. If version=None, deprecate all."""
        with self._lock:
            ids = self._name_index.get(skill_name, [])
            if not ids:
                return False
            for sid in ids:
                entry = self._entries[sid]
                if version is None or entry.version == version:
                    entry.deprecated = True
                    entry.updated_at = _now()
            self._persist_index()
            return True

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def export_skills(self, min_rating: float = 0.0) -> List[Dict[str, Any]]:
        """Export skills meeting quality threshold."""
        entries = self.search(min_rating=min_rating, limit=1000)
        result = []
        for entry in entries:
            content = self._load_content(entry.skill_id)
            d = entry.to_dict()
            d["content"] = content
            result.append(d)
        return result

    def import_skills(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Import skills from another deployment.

        Conflict resolution:
        - Same content_hash → skip (already exists)
        - Same name, different content → import as new version
        - New name → import directly
        """
        imported = 0
        skipped = 0
        for item in entries:
            name = item.get("skill_name", "")
            content = item.get("content", {})
            if not name:
                skipped += 1
                continue
            content_hash = _hash_content(content)

            with self._lock:
                # Check for existing content
                existing_ids = self._name_index.get(name, [])
                dupe = any(
                    self._entries[sid].content_hash == content_hash
                    for sid in existing_ids
                )
            if dupe:
                skipped += 1
                continue

            # Publish as new version (will auto-version)
            pub_content = dict(content)
            pub_content["description"] = item.get("description", "")
            pub_content["tags"] = item.get("tags", [])
            pub_content["author_deployment"] = item.get("author_deployment", "imported")
            self.publish(name, pub_content)
            imported += 1

        return {"imported": imported, "skipped": skipped, "total": len(entries)}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_entry(self, entry: MarketplaceEntry, content: Dict[str, Any]) -> None:
        path = _DATA_DIR / f"{entry.skill_id}.json"
        data = entry.to_dict()
        data["content"] = content
        path.write_text(json.dumps(data, indent=2))
        self._persist_index()

    def _load_content(self, skill_id: str) -> Dict[str, Any]:
        path = _DATA_DIR / f"{skill_id}.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
            return data.get("content", {})
        except (json.JSONDecodeError, OSError):
            return {}

    def _persist_index(self) -> None:
        index = {sid: e.to_dict() for sid, e in self._entries.items()}
        path = _DATA_DIR / "index.json"
        path.write_text(json.dumps(index, indent=2))

    def _load(self) -> None:
        index_path = _DATA_DIR / "index.json"
        if not index_path.exists():
            return
        try:
            index = json.loads(index_path.read_text())
            for sid, data in index.items():
                entry = MarketplaceEntry(
                    skill_id=data.get("skill_id", sid),
                    skill_name=data.get("skill_name", ""),
                    description=data.get("description", ""),
                    version=data.get("version", 1),
                    tags=data.get("tags", []),
                    success_count=data.get("success_count", 0),
                    failure_count=data.get("failure_count", 0),
                    author_deployment=data.get("author_deployment", ""),
                    content_hash=data.get("content_hash", ""),
                    deprecated=data.get("deprecated", False),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                )
                self._entries[sid] = entry
                self._name_index.setdefault(entry.skill_name, []).append(sid)
            logger.info("marketplace_loaded entries=%d", len(self._entries))
        except (json.JSONDecodeError, OSError):
            logger.warning("marketplace_load_failed", exc_info=True)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _hash_content(content: Dict[str, Any]) -> str:
    raw = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deployment_id() -> str:
    """Anonymised deployment identifier (stable per machine)."""
    import platform
    raw = f"{platform.node()}-loggerfast"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]
