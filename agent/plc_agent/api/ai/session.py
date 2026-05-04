# mypy: ignore-errors
"""
AI Session — state machine tracking the Hermes agent conversation.

Persisted to ``agent/data/ai_sessions/{session_id}/session.json`` so
conversations can resume after restart.

States:
    created → chatting → plan_proposed → awaiting_review → approved → applying → applied
                                                                               → failed
                                      → discarded
    failed / discarded / applied → chatting (restart conversation)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("loggerfast.ai.session")

# Base directory for all AI session data
_SESSIONS_BASE = Path(__file__).resolve().parents[3] / "data" / "ai_sessions"


# ---------------------------------------------------------------------------
# Session states
# ---------------------------------------------------------------------------

class SessionState(str, Enum):
    CREATED = "created"
    CHATTING = "chatting"
    PLAN_PROPOSED = "plan_proposed"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    DISCARDED = "discarded"


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED:          {SessionState.CHATTING},
    SessionState.CHATTING:         {SessionState.CHATTING, SessionState.PLAN_PROPOSED},
    SessionState.PLAN_PROPOSED:    {SessionState.AWAITING_REVIEW, SessionState.CHATTING},
    SessionState.AWAITING_REVIEW:  {SessionState.APPROVED, SessionState.DISCARDED, SessionState.CHATTING},
    SessionState.APPROVED:         {SessionState.APPLYING},
    SessionState.APPLYING:         {SessionState.APPLIED, SessionState.FAILED},
    SessionState.FAILED:           {SessionState.CHATTING},
    SessionState.DISCARDED:        {SessionState.CHATTING},
    SessionState.APPLIED:          {SessionState.CHATTING},
}


class InvalidTransition(ValueError):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: SessionState, target: SessionState):
        self.current = current
        self.target = target
        super().__init__(f"Invalid transition: {current.value} → {target.value}")


# ---------------------------------------------------------------------------
# Session class
# ---------------------------------------------------------------------------

_SESSION_FILENAME = "session.json"


class AISession:
    """Server-side session tracking AI agent conversation state."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.state = SessionState.CREATED
        self.turn_count = 0
        self.tool_call_counts: Dict[str, int] = {}
        self.created_entities: Dict[str, list] = {
            "gateway_ids": [], "device_ids": [], "schema_ids": [],
            "table_ids": [], "job_ids": [], "db_target_ids": [],
        }
        self.staged_plan: Optional[Dict[str, Any]] = None
        self.checkpoint: Optional[Dict[str, Any]] = None
        self.tool_events: list[Dict[str, Any]] = []
        self.learning_signal: Optional[Dict[str, Any]] = None
        self.iteration_count: int = 0
        self.captured_readings: list[Dict[str, Any]] = []
        self.plan_rejection_count: int = 0
        self.created_by: Optional[str] = None
        self.approved_by: Optional[str] = None
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at

    # -- state transitions ---------------------------------------------------

    def can_transition(self, target: SessionState) -> bool:
        allowed = VALID_TRANSITIONS.get(self.state, set())
        return target in allowed

    def transition(self, target: SessionState | str) -> None:
        if isinstance(target, str):
            target = SessionState(target)

        if not self.can_transition(target):
            raise InvalidTransition(self.state, target)

        old = self.state
        self.state = target

        # Clear checkpoint on successful completion
        if target == SessionState.APPLIED:
            self.checkpoint = None

        self._touch()

        logger.info("state_transition", extra={
            "session_id": self.session_id,
            "from": old.value,
            "to": target.value,
            "turn": self.turn_count,
        })

    def record_turn(self) -> None:
        self.turn_count += 1
        self._touch()

    # -- persistence ----------------------------------------------------------

    @property
    def session_dir(self) -> Path:
        return _SESSIONS_BASE / self.session_id

    @property
    def _path(self) -> Path:
        return self.session_dir / _SESSION_FILENAME

    def save(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    @classmethod
    def load(cls, session_id: str) -> "AISession":
        path = _SESSIONS_BASE / session_id / _SESSION_FILENAME
        if not path.exists():
            raise FileNotFoundError(f"No session at {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        session = cls(session_id=data.get("session_id", session_id))
        session.state = SessionState(data.get("state", "created"))
        session.turn_count = data.get("turn_count", 0)
        session.tool_call_counts = data.get("tool_call_counts", {})
        session.created_entities = data.get("created_entities", {
            "gateway_ids": [], "device_ids": [], "schema_ids": [],
            "table_ids": [], "job_ids": [], "db_target_ids": [],
        })
        session.staged_plan = data.get("staged_plan")
        session.checkpoint = data.get("checkpoint")
        session.tool_events = data.get("tool_events", [])
        session.learning_signal = data.get("learning_signal")
        session.iteration_count = data.get("iteration_count", 0)
        session.captured_readings = data.get("captured_readings", [])
        session.plan_rejection_count = data.get("plan_rejection_count", 0)
        session.created_by = data.get("created_by")
        session.approved_by = data.get("approved_by")
        session.created_at = data.get("created_at", session.created_at)
        session.updated_at = data.get("updated_at", session.updated_at)
        return session

    @classmethod
    def create(cls) -> "AISession":
        session = cls()
        session.save()
        return session

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "turn_count": self.turn_count,
            "tool_call_counts": self.tool_call_counts,
            "created_entities": self.created_entities,
            "staged_plan": self.staged_plan,
            "checkpoint": self.checkpoint,
            "tool_events": self.tool_events,
            "learning_signal": self.learning_signal,
            "iteration_count": self.iteration_count,
            "captured_readings": self.captured_readings,
            "plan_rejection_count": self.plan_rejection_count,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def track_entity(self, entity_type: str, entity_id: str) -> None:
        """Append an entity ID to the created_entities tracker."""
        key = f"{entity_type}_ids"
        if key in self.created_entities:
            if entity_id not in self.created_entities[key]:
                self.created_entities[key].append(entity_id)
            self._touch()

    # -- trace / iteration tracking -------------------------------------------

    def record_tool_event(self, event: dict) -> None:
        """Append a tool invocation record to the audit trail."""
        self.tool_events.append(event)
        self.iteration_count += 1
        self._touch()

    def reset_iteration_count(self) -> None:
        """Reset per-turn iteration counter (called at start of each turn)."""
        self.iteration_count = 0

    # -- checkpoint / recovery ------------------------------------------------

    def save_checkpoint(
        self,
        tool_name: str,
        tool_args: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Save a checkpoint during APPLYING for failure recovery.

        Called by CallbackBridge.on_tool_complete for write tools so that
        on FAILED → CHATTING the LLM knows where execution stopped.
        """
        self.checkpoint = {
            "last_tool": tool_name,
            "last_tool_args": tool_args or {},
            "error": error,
            "created_entities_snapshot": {
                k: list(v) for k, v in self.created_entities.items()
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._touch()

    def get_recovery_context(self) -> Optional[Dict[str, Any]]:
        """Return checkpoint + plan context for resuming after failure.

        Returns None if no recovery context is available.
        """
        if self.checkpoint is None and self.staged_plan is None:
            return None
        return {
            "checkpoint": self.checkpoint,
            "staged_plan": self.staged_plan,
            "created_entities": self.created_entities,
        }

    # -- helpers --------------------------------------------------------------

    def _touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def __repr__(self) -> str:
        return (
            f"<AISession {self.session_id} "
            f"state={self.state.value} "
            f"turns={self.turn_count}>"
        )
