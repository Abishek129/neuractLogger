# mypy: ignore-errors
"""Phase 3D — Multi-session coordinator for large site configuration.

Allows parallel AI sessions to work on different site sections without
entity name conflicts.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("loggerfast.ai.multi_session")

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "ai_session_groups"


@dataclass
class SessionGroup:
    """Coordinates multiple AI sessions working on the same site."""
    group_id: str
    name: str
    session_ids: list[str] = field(default_factory=list)
    scopes: Dict[str, str] = field(default_factory=dict)         # session_id -> scope
    entity_locks: Dict[str, str] = field(default_factory=dict)   # entity_name -> session_id
    created_at: str = ""
    status: str = "active"  # active | completed | partial

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "name": self.name,
            "session_ids": self.session_ids,
            "scopes": self.scopes,
            "entity_locks": self.entity_locks,
            "lock_count": len(self.entity_locks),
            "created_at": self.created_at,
            "status": self.status,
        }


class SessionCoordinator:
    """Coordinates multiple AI sessions to prevent entity conflicts."""

    _instance: Optional["SessionCoordinator"] = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._groups: Dict[str, SessionGroup] = {}
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    @classmethod
    def instance(cls) -> "SessionCoordinator":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = SessionCoordinator()
            return cls._instance

    # ------------------------------------------------------------------
    # Group management
    # ------------------------------------------------------------------

    def create_group(self, name: str) -> SessionGroup:
        """Create a new session group for a site."""
        group = SessionGroup(
            group_id=uuid.uuid4().hex[:12],
            name=name,
            created_at=_now(),
        )
        with self._lock:
            self._groups[group.group_id] = group
            self._persist(group)
        logger.info("session_group_created id=%s name=%s", group.group_id, name)
        return group

    def add_session(
        self, group_id: str, session_id: str, scope: str,
    ) -> bool:
        """Add a session to a group with scope description."""
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return False
            if session_id not in group.session_ids:
                group.session_ids.append(session_id)
            group.scopes[session_id] = scope
            self._persist(group)
        return True

    def get_group(self, group_id: str) -> Optional[SessionGroup]:
        with self._lock:
            return self._groups.get(group_id)

    def list_groups(self) -> List[SessionGroup]:
        with self._lock:
            return list(self._groups.values())

    def find_group_for_session(self, session_id: str) -> Optional[SessionGroup]:
        """Find which group a session belongs to (if any)."""
        with self._lock:
            for group in self._groups.values():
                if session_id in group.session_ids:
                    return group
        return None

    # ------------------------------------------------------------------
    # Entity locking
    # ------------------------------------------------------------------

    def acquire_lock(
        self,
        group_id: str,
        session_id: str,
        entity_type: str,
        entity_name: str,
    ) -> bool:
        """Try to acquire an entity lock. Returns False if locked by another session."""
        key = f"{entity_type}:{entity_name}"
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return False
            owner = group.entity_locks.get(key)
            if owner and owner != session_id:
                return False  # locked by someone else
            group.entity_locks[key] = session_id
            self._persist(group)
        return True

    def release_lock(
        self,
        group_id: str,
        session_id: str,
        entity_name: str,
    ) -> None:
        """Release a specific entity lock."""
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return
            to_remove = [
                k for k, v in group.entity_locks.items()
                if v == session_id and entity_name in k
            ]
            for k in to_remove:
                del group.entity_locks[k]
            self._persist(group)

    def release_all_locks(self, group_id: str, session_id: str) -> int:
        """Release all locks held by a session. Returns count released."""
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return 0
            to_remove = [
                k for k, v in group.entity_locks.items() if v == session_id
            ]
            for k in to_remove:
                del group.entity_locks[k]
            self._persist(group)
            return len(to_remove)

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def check_conflicts(self, group_id: str) -> List[Dict[str, Any]]:
        """Check for any entity conflicts across sessions in the group."""
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return []
            # Conflicts = same entity type+name locked by different sessions
            # (shouldn't happen with locking, but check for debugging)
            conflicts = []
            seen: Dict[str, str] = {}
            for key, owner in group.entity_locks.items():
                entity_name = key.split(":", 1)[-1] if ":" in key else key
                if entity_name in seen and seen[entity_name] != owner:
                    conflicts.append({
                        "entity": entity_name,
                        "sessions": [seen[entity_name], owner],
                    })
                seen[entity_name] = owner
            return conflicts

    def get_group_status(self, group_id: str) -> Dict[str, Any]:
        """Aggregate status across all sessions in the group."""
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return {"error": "GROUP_NOT_FOUND"}
            return {
                **group.to_dict(),
                "session_count": len(group.session_ids),
                "conflicts": self.check_conflicts(group_id),
            }

    # ------------------------------------------------------------------
    # Session completion
    # ------------------------------------------------------------------

    def complete_session(self, group_id: str, session_id: str) -> None:
        """Mark a session as complete, release all its locks."""
        released = self.release_all_locks(group_id, session_id)
        with self._lock:
            group = self._groups.get(group_id)
            if group:
                # Check if all sessions are done
                all_done = all(
                    sid == session_id or sid not in [
                        k for k in group.entity_locks.values()
                    ]
                    for sid in group.session_ids
                )
                if all_done and not group.entity_locks:
                    group.status = "completed"
                self._persist(group)
        logger.info(
            "session_completed group=%s session=%s locks_released=%d",
            group_id, session_id, released,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, group: SessionGroup) -> None:
        path = _DATA_DIR / f"{group.group_id}.json"
        path.write_text(json.dumps(group.to_dict(), indent=2))

    def _load(self) -> None:
        if not _DATA_DIR.exists():
            return
        for path in _DATA_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                group = SessionGroup(
                    group_id=data.get("group_id", path.stem),
                    name=data.get("name", ""),
                    session_ids=data.get("session_ids", []),
                    scopes=data.get("scopes", {}),
                    entity_locks=data.get("entity_locks", {}),
                    created_at=data.get("created_at", ""),
                    status=data.get("status", "active"),
                )
                self._groups[group.group_id] = group
            except (json.JSONDecodeError, OSError):
                continue
        if self._groups:
            logger.info("session_groups_loaded count=%d", len(self._groups))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
