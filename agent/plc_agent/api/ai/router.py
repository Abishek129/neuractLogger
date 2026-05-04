# mypy: ignore-errors
"""
AI Router — FastAPI endpoints for the Hermes AI agent.

Endpoints:
    POST /ai/sessions              — create a new AI chat session
    POST /ai/sessions/{id}/chat    — send a message, get NDJSON stream back
    GET  /ai/sessions/{id}         — get session state
    POST /ai/raw_read              — raw Modbus/OPC UA read (no session needed)
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..permissions import get_claims  # used by session entry endpoints
from ..security import decode_jwt, extract_bearer_token
from .session import AISession, _SESSIONS_BASE

logger = logging.getLogger("loggerfast.ai.router")

router = APIRouter(prefix="/ai", tags=["ai"])


def _username(claims: dict) -> str:
    """Extract display username from JWT claims."""
    return claims.get("preferred_username") or claims.get("sub", "unknown")


def _has_write(claims: dict) -> bool:
    """Check if user has logger_write realm role."""
    roles = (claims.get("realm_access") or {}).get("roles") or []
    return "logger_write" in roles or "logger-write" in roles


def _try_extract_user(request) -> Optional[str]:
    """Best-effort username extraction from Bearer token. Returns None if absent/invalid."""
    try:
        token = extract_bearer_token(request.headers.get("authorization"))
        if not token:
            token = request.headers.get("x-agent-token") or None
        if token:
            claims = decode_jwt(token)
            return _username(claims)
    except Exception:
        pass
    return None

# Concurrent session guard — prevents two simultaneous chats to the same session
_session_locks: Dict[str, asyncio.Lock] = {}

# Phase 1F — KB sub-router
try:
    from .mfm_kb.router import kb_router
    router.include_router(kb_router)
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateSessionResponse(BaseModel):
    session_id: str
    state: str
    user: Optional[str] = None
    can_write: bool = False


class ChatRequest(BaseModel):
    message: str


class SessionResponse(BaseModel):
    session_id: str
    state: str
    turn_count: int
    created_at: str
    updated_at: str
    tool_count: int = 0
    available_tools: list[str] = []
    user: Optional[str] = None
    can_write: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/sessions")
def list_sessions():
    """List all AI sessions (lightweight summaries)."""
    sessions = []
    if _SESSIONS_BASE.exists():
        for d in sorted(_SESSIONS_BASE.iterdir(), reverse=True):
            path = d / "session.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    sessions.append({
                        "session_id": data.get("session_id", d.name),
                        "state": data.get("state", "unknown"),
                        "turn_count": data.get("turn_count", 0),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                    })
                except Exception:
                    pass
    return {"sessions": sessions, "count": len(sessions)}


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session(claims: dict = Depends(get_claims)):
    """Create a new AI chat session."""
    session = AISession.create()
    session.created_by = _username(claims)
    session.save()
    logger.info("session_created", extra={"session_id": session.session_id, "user": session.created_by})
    return CreateSessionResponse(
        session_id=session.session_id,
        state=session.state.value,
        user=session.created_by,
        can_write=_has_write(claims),
    )


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: str, body: ChatRequest):
    """Send a message and get an NDJSON stream of events back.

    The response is ``application/x-ndjson`` — one JSON object per line.
    Events: ``chat_start``, ``stage`` (tool progress), ``chat_complete``.
    """
    lock = _get_session_lock(session_id)
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail="SESSION_BUSY — another chat request is already running for this session",
        )

    async with lock:
        # Load session
        try:
            session = AISession.load(session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

        # Validate message
        message = body.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="EMPTY_MESSAGE")

        # Lazy import to avoid import-time side effects from hermes-agent
        from .hermes_agent import HermesAgent

        agent = HermesAgent(session)

        async def event_stream():
            try:
                async for event in agent.run(message):
                    yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
            except Exception as exc:
                logger.exception("chat_stream_error", extra={
                    "session_id": session_id,
                })
                yield json.dumps({
                    "event": "error",
                    "message": str(exc),
                }) + "\n"

        return StreamingResponse(
            event_stream(),
            media_type="application/x-ndjson",
        )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, claims: dict = Depends(get_claims)):
    """Get session state."""
    try:
        session = AISession.load(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

    from .tools import TOOL_DISPATCH

    return SessionResponse(
        session_id=session.session_id,
        state=session.state.value,
        turn_count=session.turn_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
        tool_count=len(TOOL_DISPATCH),
        available_tools=sorted(TOOL_DISPATCH.keys()),
        user=_username(claims),
        can_write=_has_write(claims),
    )


@router.get("/sessions/{session_id}/history")
def get_session_history(session_id: str):
    """Get the persisted chat history for a session."""
    try:
        session = AISession.load(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

    from .chat_history import ChatHistory

    history = ChatHistory.load(session.session_dir)
    return {
        "session_id": session_id,
        "messages": history.messages,
        "count": len(history.messages),
    }


# ---------------------------------------------------------------------------
# Delete session endpoint
# ---------------------------------------------------------------------------

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, claims: dict = Depends(get_claims)):
    """Delete an AI session and all its data (history, trace, etc.)."""
    try:
        session = AISession.load(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

    # Don't delete sessions that are actively running
    lock = _get_session_lock(session_id)
    if lock.locked():
        raise HTTPException(status_code=409, detail="SESSION_BUSY — cannot delete while active")

    import shutil
    session_dir = session.session_dir
    if session_dir.exists():
        shutil.rmtree(session_dir)
    _session_locks.pop(session_id, None)

    logger.info("session_deleted", extra={"session_id": session_id, "user": _username(claims)})
    return {"status": "ok", "session_id": session_id, "deleted": True}


# ---------------------------------------------------------------------------
# Trace endpoint
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/trace")
def get_session_trace(session_id: str):
    """Full audit log of every tool call in this session."""
    try:
        session = AISession.load(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "turn_count": session.turn_count,
        "iteration_count": session.iteration_count,
        "tool_events": session.tool_events,
        "event_count": len(session.tool_events),
        "learning_signal": session.learning_signal,
    }


# ---------------------------------------------------------------------------
# Approval endpoints
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    message: str = ""


def _get_session_lock(session_id: str) -> asyncio.Lock:
    """Get or create a per-session lock."""
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


@router.post("/sessions/{session_id}/approve")
async def approve_plan(session_id: str, request: Request, body: ApproveRequest = ApproveRequest()):
    """Approve a staged configuration plan for execution.

    Session must be in 'plan_proposed' or 'awaiting_review' state.
    Transitions to 'approved'. Identity captured from Bearer token if present,
    otherwise falls back to session creator.
    """
    lock = _get_session_lock(session_id)
    if lock.locked():
        raise HTTPException(status_code=409, detail="SESSION_BUSY")

    try:
        session = AISession.load(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

    from .session import SessionState

    if session.state == SessionState.PLAN_PROPOSED:
        session.transition(SessionState.AWAITING_REVIEW)
        session.transition(SessionState.APPROVED)
    elif session.state == SessionState.AWAITING_REVIEW:
        session.transition(SessionState.APPROVED)
    else:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: session is in '{session.state.value}' state.",
        )

    session.approved_by = _try_extract_user(request) or session.created_by or "unknown"
    session.save()
    logger.info("plan_approved", extra={"session_id": session_id, "approved_by": session.approved_by})

    return {
        "status": "ok",
        "session_id": session_id,
        "state": session.state.value,
        "approved_by": session.approved_by,
        "plan_summary": (session.staged_plan or {}).get("summary"),
    }


@router.post("/sessions/{session_id}/discard")
async def discard_plan(session_id: str):
    """Discard a staged plan. Transitions to 'discarded' state."""
    lock = _get_session_lock(session_id)
    if lock.locked():
        raise HTTPException(status_code=409, detail="SESSION_BUSY")

    try:
        session = AISession.load(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

    from .session import SessionState

    if session.state not in (SessionState.PLAN_PROPOSED, SessionState.AWAITING_REVIEW):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot discard: session is in '{session.state.value}' state.",
        )

    if session.state == SessionState.PLAN_PROPOSED:
        session.transition(SessionState.AWAITING_REVIEW)
    session.transition(SessionState.DISCARDED)
    session.staged_plan = None
    session.plan_rejection_count += 1
    session.save()

    return {"status": "ok", "session_id": session_id, "state": session.state.value}


@router.post("/sessions/{session_id}/apply")
async def apply_plan(session_id: str):
    """Execute the approved plan. Streams NDJSON progress events.

    The session must be in 'approved' state. This sends a synthetic
    "execute the approved plan" message through the agent, which triggers
    the write tools. Equivalent to the user sending "go ahead" in chat.
    """
    lock = _get_session_lock(session_id)
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail="SESSION_BUSY — another request is already running for this session",
        )

    async with lock:
        try:
            session = AISession.load(session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

        from .session import SessionState

        if session.state != SessionState.APPROVED:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot apply: session is in '{session.state.value}' state. Expected 'approved'.",
            )

        from .hermes_agent import HermesAgent

        agent = HermesAgent(session)

        async def event_stream():
            try:
                async for event in agent.run(
                    "The engineer has approved the plan. Execute it now — "
                    "create all entities in dependency order."
                ):
                    yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
            except Exception as exc:
                logger.exception("apply_stream_error", extra={"session_id": session_id})
                yield json.dumps({"event": "error", "message": str(exc)}) + "\n"

        return StreamingResponse(event_stream(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# Prediction API (Phase 3A — Layer 3)
# ---------------------------------------------------------------------------


@router.get("/predictions")
def get_all_predictions():
    """Get Layer 3 prediction status for all monitored devices."""
    try:
        from .prediction.monitor import PredictionManager
    except ImportError:
        raise HTTPException(status_code=501, detail="PREDICTION_MODULE_UNAVAILABLE")
    manager = PredictionManager.instance()
    statuses = manager.get_all_statuses()
    return {
        "device_count": len(statuses),
        "devices": [s.to_dict() for s in statuses],
    }


@router.get("/predictions/{device_id}")
def get_device_prediction(device_id: str):
    """Get Layer 3 prediction status for a specific device."""
    try:
        from .prediction.monitor import PredictionManager
    except ImportError:
        raise HTTPException(status_code=501, detail="PREDICTION_MODULE_UNAVAILABLE")
    manager = PredictionManager.instance()
    status = manager.get_status(device_id)
    if status is None:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_MONITORED")
    return {"device_id": device_id, "prediction": status.to_dict()}


class PredictionConfigRequest(BaseModel):
    window_size: Optional[int] = None
    sigma_threshold: Optional[float] = None
    drift_sigma: Optional[float] = None
    trend_slope_threshold: Optional[float] = None
    trend_r2_threshold: Optional[float] = None
    hw_alpha: Optional[float] = None
    hw_beta: Optional[float] = None
    alert_cooldown_s: Optional[float] = None


@router.post("/predictions/configure")
def configure_predictions(body: PredictionConfigRequest):
    """Update Layer 3 prediction configuration at runtime."""
    try:
        from .prediction.monitor import PredictionManager
    except ImportError:
        raise HTTPException(status_code=501, detail="PREDICTION_MODULE_UNAVAILABLE")
    manager = PredictionManager.instance()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="NO_FIELDS_TO_UPDATE")
    manager.configure(**updates)
    return {"status": "ok", "updated": list(updates.keys())}


# ---------------------------------------------------------------------------
# Temporal Model API (Phase 3B — Layer 3 TCN)
# ---------------------------------------------------------------------------


@router.get("/predictions/temporal")
def get_all_temporal_statuses():
    """Get temporal model status for all monitored devices."""
    try:
        from .prediction.temporal_monitor import TemporalManager
    except ImportError:
        raise HTTPException(status_code=501, detail="TEMPORAL_MODULE_UNAVAILABLE")
    manager = TemporalManager.instance()
    statuses = manager.get_all_statuses()
    return {
        "device_count": len(statuses),
        "devices": [s.to_dict() for s in statuses],
    }


@router.get("/predictions/temporal/{device_id}")
def get_device_temporal_status(device_id: str):
    """Get temporal model status for a specific device."""
    try:
        from .prediction.temporal_monitor import TemporalManager
    except ImportError:
        raise HTTPException(status_code=501, detail="TEMPORAL_MODULE_UNAVAILABLE")
    manager = TemporalManager.instance()
    status = manager.get_status(device_id)
    if status is None:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_MONITORED")
    return {"device_id": device_id, "temporal": status.to_dict()}


@router.post("/predictions/temporal/{device_id}/retrain")
async def retrain_temporal_model_endpoint(device_id: str):
    """Trigger retraining of a device's temporal model."""
    try:
        from .prediction.temporal_monitor import TemporalManager
    except ImportError:
        raise HTTPException(status_code=501, detail="TEMPORAL_MODULE_UNAVAILABLE")
    import asyncio
    manager = TemporalManager.instance()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: manager.trigger_retrain(device_id))
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"status": "ok", **result}


class TemporalConfigRequest(BaseModel):
    baseline_samples: Optional[int] = None
    max_baseline: Optional[int] = None
    retrain_interval: Optional[float] = None
    alert_cooldown: Optional[float] = None
    anomaly_threshold: Optional[float] = None
    score_smoothing: Optional[int] = None


@router.post("/predictions/temporal/configure")
def configure_temporal(body: TemporalConfigRequest):
    """Update temporal model configuration at runtime."""
    try:
        from .prediction.temporal_monitor import TemporalManager
    except ImportError:
        raise HTTPException(status_code=501, detail="TEMPORAL_MODULE_UNAVAILABLE")
    manager = TemporalManager.instance()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="NO_FIELDS_TO_UPDATE")
    manager.configure(**updates)
    return {"status": "ok", "updated": list(updates.keys())}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Topology API (Phase 3D)
# ---------------------------------------------------------------------------


@router.get("/topology")
def get_all_topologies():
    """Get all inferred topologies."""
    try:
        from ..appdb import _conn
        from sqlalchemy import text
    except ImportError:
        raise HTTPException(status_code=501, detail="DB_UNAVAILABLE")
    try:
        with _conn() as c:
            rows = c.execute(text("SELECT * FROM app_device_topology")).mappings().all()
        devices = [dict(r) for r in rows]
        return {"device_count": len(devices), "devices": devices}
    except Exception:
        return {"device_count": 0, "devices": [], "message": "No topology data (DB not configured)."}


@router.get("/topology/{gateway_id}")
def get_gateway_topology(gateway_id: str):
    """Get topology for a specific gateway."""
    try:
        from ..appdb import _conn
        from sqlalchemy import text
    except ImportError:
        raise HTTPException(status_code=501, detail="DB_UNAVAILABLE")
    try:
        with _conn() as c:
            rows = c.execute(text(
                "SELECT * FROM app_device_topology WHERE gateway_id = :gid"
            ), {"gid": gateway_id}).mappings().all()
        if not rows:
            raise HTTPException(status_code=404, detail="NO_TOPOLOGY_FOR_GATEWAY")
        return {"gateway_id": gateway_id, "devices": [dict(r) for r in rows]}
    except HTTPException:
        raise
    except Exception:
        return {"gateway_id": gateway_id, "devices": [], "message": "No topology data."}


@router.post("/topology/infer")
async def infer_topology_endpoint(body: dict):
    """Trigger SLD topology inference for a gateway."""
    gateway_id = body.get("gateway_id", "")
    if not gateway_id:
        raise HTTPException(status_code=422, detail="GATEWAY_ID_REQUIRED")
    snapshots = body.get("snapshots", 1)

    try:
        from .topology.inference import TopologyInferenceEngine
        from .topology.naming import suggest_names
    except ImportError:
        raise HTTPException(status_code=501, detail="TOPOLOGY_MODULE_UNAVAILABLE")

    try:
        from ..store import Store
        from ..routers.jobs import _read_mapping_values
    except ImportError:
        raise HTTPException(status_code=501, detail="STORE_UNAVAILABLE")

    import asyncio
    store = Store.instance()
    devices_data = []
    loop = asyncio.get_running_loop()
    for dev in store.list_devices():
        if dev.get("gatewayId") != gateway_id and dev.get("gateway_id") != gateway_id:
            continue
        dev_id = dev.get("id")
        for tbl in store.list_tables():
            mapping = store.get_mapping(tbl.get("id", ""))
            if mapping and mapping.get("deviceId") == dev_id:
                try:
                    values = await loop.run_in_executor(
                        None, lambda tid=tbl["id"]: _read_mapping_values(tid))
                    devices_data.append({
                        "device_id": dev_id, "device_name": dev.get("name", dev_id),
                        "gateway_id": gateway_id, "readings": values,
                    })
                except Exception:
                    pass
                break

    if len(devices_data) < 2:
        raise HTTPException(status_code=422, detail="INSUFFICIENT_DEVICES")

    engine = TopologyInferenceEngine()
    graph = engine.infer(devices_data, snapshots=snapshots)
    names = suggest_names(graph)
    result = graph.to_dict()
    result["suggested_names"] = names
    return result


@router.put("/topology/{device_id}")
def update_device_topology(device_id: str, body: dict):
    """Manually override a device's topology classification."""
    try:
        from ..appdb import _conn
        from sqlalchemy import text
    except ImportError:
        raise HTTPException(status_code=501, detail="DB_UNAVAILABLE")

    level = body.get("hierarchy_level")
    pattern = body.get("load_pattern")
    parent = body.get("parent_device_id")

    updates = {}
    if level:
        updates["hierarchy_level"] = level
    if pattern:
        updates["load_pattern"] = pattern
    if parent is not None:
        updates["parent_device_id"] = parent
    if not updates:
        raise HTTPException(status_code=422, detail="NO_FIELDS_TO_UPDATE")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["did"] = device_id

    with _conn() as c:
        result = c.execute(text(
            f"UPDATE app_device_topology SET {set_clause} WHERE device_id = :did"
        ), updates)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="DEVICE_NOT_IN_TOPOLOGY")

    return {"status": "ok", "device_id": device_id, "updated": list(updates.keys() - {"did"})}


# ---------------------------------------------------------------------------
# Marketplace API (Phase 3D)
# ---------------------------------------------------------------------------


@router.get("/marketplace")
def marketplace_search_endpoint(
    query: str = "", tags: str = "", min_rating: float = 0.0,
):
    """Search skill marketplace."""
    try:
        from .marketplace import SkillMarketplace
    except ImportError:
        raise HTTPException(status_code=501, detail="MARKETPLACE_UNAVAILABLE")
    mp = SkillMarketplace.instance()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = mp.search(query=query, tags=tag_list, min_rating=min_rating)
    return {"result_count": len(results), "skills": [e.to_dict() for e in results]}


@router.get("/marketplace/{skill_id}")
def marketplace_get_entry(skill_id: str):
    """Get a specific marketplace entry."""
    try:
        from .marketplace import SkillMarketplace
    except ImportError:
        raise HTTPException(status_code=501, detail="MARKETPLACE_UNAVAILABLE")
    mp = SkillMarketplace.instance()
    entry = mp.get_entry(skill_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="SKILL_NOT_FOUND")
    return entry.to_dict()


@router.post("/marketplace/import")
def marketplace_import_endpoint(body: dict):
    """Bulk import skills from another deployment."""
    try:
        from .marketplace import SkillMarketplace
    except ImportError:
        raise HTTPException(status_code=501, detail="MARKETPLACE_UNAVAILABLE")
    mp = SkillMarketplace.instance()
    entries = body.get("skills", [])
    result = mp.import_skills(entries)
    return result


@router.get("/marketplace/export")
def marketplace_export_endpoint(min_rating: float = 0.0):
    """Export marketplace skills."""
    try:
        from .marketplace import SkillMarketplace
    except ImportError:
        raise HTTPException(status_code=501, detail="MARKETPLACE_UNAVAILABLE")
    mp = SkillMarketplace.instance()
    return {"skills": mp.export_skills(min_rating=min_rating)}


@router.post("/marketplace/publish")
def marketplace_publish_endpoint(body: dict):
    """Publish a skill to the marketplace."""
    try:
        from .marketplace import SkillMarketplace
    except ImportError:
        raise HTTPException(status_code=501, detail="MARKETPLACE_UNAVAILABLE")
    skill_name = body.get("skill_name", "")
    if not skill_name:
        raise HTTPException(status_code=422, detail="SKILL_NAME_REQUIRED")
    mp = SkillMarketplace.instance()
    entry = mp.publish(skill_name, body)
    return entry.to_dict()


@router.post("/marketplace/{skill_id}/rate")
def marketplace_rate_endpoint(skill_id: str, body: dict):
    """Record a skill usage outcome (success/failure)."""
    try:
        from .marketplace import SkillMarketplace
    except ImportError:
        raise HTTPException(status_code=501, detail="MARKETPLACE_UNAVAILABLE")
    success = body.get("success", True)
    mp = SkillMarketplace.instance()
    mp.record_outcome(skill_id, success=success)
    return {"status": "ok", "skill_id": skill_id, "success": success}


# ---------------------------------------------------------------------------
# Session Groups API (Phase 3D — Multi-Session)
# ---------------------------------------------------------------------------


@router.post("/session-groups")
def create_session_group_endpoint(body: dict):
    """Create a multi-session group."""
    try:
        from .multi_session import SessionCoordinator
    except ImportError:
        raise HTTPException(status_code=501, detail="MULTI_SESSION_UNAVAILABLE")
    name = body.get("name", "")
    if not name:
        raise HTTPException(status_code=422, detail="NAME_REQUIRED")
    coord = SessionCoordinator.instance()
    group = coord.create_group(name)
    return group.to_dict()


@router.get("/session-groups")
def list_session_groups():
    """List all session groups."""
    try:
        from .multi_session import SessionCoordinator
    except ImportError:
        raise HTTPException(status_code=501, detail="MULTI_SESSION_UNAVAILABLE")
    coord = SessionCoordinator.instance()
    groups = coord.list_groups()
    return {"groups": [g.to_dict() for g in groups], "count": len(groups)}


@router.get("/session-groups/{group_id}")
def get_session_group(group_id: str):
    """Get group status + conflicts."""
    try:
        from .multi_session import SessionCoordinator
    except ImportError:
        raise HTTPException(status_code=501, detail="MULTI_SESSION_UNAVAILABLE")
    coord = SessionCoordinator.instance()
    status = coord.get_group_status(group_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return status


@router.post("/session-groups/{group_id}/join")
def join_session_group(group_id: str, body: dict):
    """Add a session to a group."""
    try:
        from .multi_session import SessionCoordinator
    except ImportError:
        raise HTTPException(status_code=501, detail="MULTI_SESSION_UNAVAILABLE")
    session_id = body.get("session_id", "")
    scope = body.get("scope", "default")
    if not session_id:
        raise HTTPException(status_code=422, detail="SESSION_ID_REQUIRED")
    coord = SessionCoordinator.instance()
    ok = coord.add_session(group_id, session_id, scope)
    if not ok:
        raise HTTPException(status_code=404, detail="GROUP_NOT_FOUND")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Training Data API (Phase 2C)
# ---------------------------------------------------------------------------

@router.get("/anomaly/training-data")
def list_training_datasets():
    """List all anomaly training datasets per model."""
    from .validation.training_data import load_training_index
    return {"datasets": load_training_index()}


@router.get("/anomaly/training-data/{model}/export")
def export_training_dataset(model: str):
    """Download a model's training dataset as .npz."""
    from .validation.training_data import export_dataset
    from .validation.anomaly import _sanitize_key
    key = _sanitize_key(model)
    data = export_dataset(key)
    if data is None:
        raise HTTPException(status_code=404, detail="DATASET_NOT_FOUND")
    from fastapi.responses import Response
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={key}_dataset.npz"},
    )


@router.post("/anomaly/training-data/{model}/import")
async def import_training_dataset(model: str, request=None):
    """Import a training dataset from .npz bytes."""
    from .validation.training_data import import_dataset
    from .validation.anomaly import _sanitize_key
    from fastapi import Request
    if request is None:
        raise HTTPException(status_code=400, detail="NO_DATA")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="EMPTY_BODY")
    key = _sanitize_key(model)
    try:
        total = import_dataset(key, body)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"status": "ok", "model": key, "total_samples": total}


@router.post("/anomaly/retrain/{model}")
async def retrain_anomaly(model: str):
    """Trigger retraining of an anomaly model with real + synthetic data."""
    from .validation.anomaly import AnomalyDetector, _sanitize_key
    from .mfm_kb.manager import KBManager
    import asyncio

    key = _sanitize_key(model)
    mgr = KBManager.instance()
    kb_entry = mgr.get_entry(model)
    if kb_entry is None:
        raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")

    regs = kb_entry.registers
    kb_regs = [r.model_dump() if hasattr(r, "model_dump") else r for r in regs]
    detector = AnomalyDetector.instance()

    loop = asyncio.get_running_loop()
    stats = await loop.run_in_executor(None, lambda: detector.retrain_model(key, kb_regs))
    return {"status": "ok", **stats}


# ---------------------------------------------------------------------------
# Skills API (Phase 2A)
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path.home() / ".hermes" / "skills"


def _parse_skill_frontmatter(skill_dir: Path) -> dict:
    """Parse SKILL.md YAML frontmatter from a skill directory."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {"name": skill_dir.name, "description": ""}
    try:
        text = skill_md.read_text(encoding="utf-8")
        # Extract YAML frontmatter between --- delimiters
        if text.startswith("---"):
            end = text.find("---", 3)
            if end > 0:
                import yaml
                meta = yaml.safe_load(text[3:end]) or {}
                meta.setdefault("name", skill_dir.name)
                meta["content_preview"] = text[end + 3:end + 503].strip()
                return meta
        return {"name": skill_dir.name, "description": "", "content_preview": text[:500]}
    except Exception:
        return {"name": skill_dir.name, "description": ""}


@router.get("/skills")
def list_skills():
    """List all learned skills."""
    if not _SKILLS_DIR.exists():
        return {"skills": [], "count": 0}
    skills = []
    for d in sorted(_SKILLS_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            meta = _parse_skill_frontmatter(d)
            meta["id"] = d.name
            skills.append(meta)
    return {"skills": skills, "count": len(skills)}


@router.get("/skills/export")
def export_skills():
    """Export all skills as JSON (portable across deployments)."""
    if not _SKILLS_DIR.exists():
        return {"skills": []}
    exported = []
    for d in sorted(_SKILLS_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            files = {}
            for f in d.rglob("*"):
                if f.is_file():
                    rel = str(f.relative_to(d))
                    try:
                        files[rel] = f.read_text(encoding="utf-8")
                    except Exception:
                        pass
            exported.append({"name": d.name, "files": files})
    return {"skills": exported, "count": len(exported)}


@router.post("/skills/import")
def import_skills(body: dict):
    """Import skills from JSON export."""
    skills = body.get("skills", [])
    if not skills:
        raise HTTPException(status_code=422, detail="NO_SKILLS")
    imported = 0
    for skill in skills:
        name = skill.get("name", "").strip()
        if not name:
            continue
        skill_dir = _SKILLS_DIR / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        for rel_path, content in skill.get("files", {}).items():
            target = skill_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        imported += 1
    return {"status": "ok", "imported": imported}


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str):
    """Get a specific skill's full content."""
    skill_dir = _SKILLS_DIR / skill_id
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="SKILL_NOT_FOUND")
    meta = _parse_skill_frontmatter(skill_dir)
    meta["id"] = skill_id
    # Include full SKILL.md content
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        meta["content"] = skill_md.read_text(encoding="utf-8")
    return meta


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str):
    """Remove a skill."""
    skill_dir = _SKILLS_DIR / skill_id
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="SKILL_NOT_FOUND")
    import shutil
    shutil.rmtree(skill_dir)
    logger.info("skill_deleted", extra={"skill_id": skill_id})
    return {"status": "ok", "skill_id": skill_id}


# ---------------------------------------------------------------------------
# Raw read endpoint (no session needed)
# ---------------------------------------------------------------------------

class RawReadRequest(BaseModel):
    ip: str
    port: int = 502
    unit_id: int = 1
    start_address: int = 0
    count: int = 1
    protocol: str = "modbus"  # "modbus" or "opcua"
    data_type: str = "uint16"
    node_id: Optional[str] = None


@router.post("/raw_read")
async def raw_read(body: RawReadRequest):
    """Raw Modbus register read or OPC UA node browse — no session needed."""
    from .tools import read_raw_registers, browse_opcua_nodes, ToolContext

    # Throwaway context (no real session for raw reads)
    dummy_session = AISession.__new__(AISession)
    dummy_session.session_id = "raw_read"
    dummy_session.tool_call_counts = {}
    ctx = ToolContext(
        session=dummy_session,
        event_queue=asyncio.Queue(),
        tool_call_counts={},
    )

    if body.protocol == "modbus":
        result = await read_raw_registers(
            ctx, ip=body.ip, port=body.port, unit_id=body.unit_id,
            start_address=body.start_address, count=body.count,
            data_type=body.data_type,
        )
    elif body.protocol == "opcua":
        endpoint = f"opc.tcp://{body.ip}:{body.port}"
        result = await browse_opcua_nodes(
            ctx, endpoint=endpoint, node_id=body.node_id or "i=85",
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported protocol: {body.protocol}")

    if "error" in result:
        raise HTTPException(status_code=502, detail=result)
    return result


# ---------------------------------------------------------------------------
# Static UI files (Phase 3C)
# ---------------------------------------------------------------------------

from fastapi.staticfiles import StaticFiles

_UI_DIR = Path(__file__).resolve().parent / "ui"
if _UI_DIR.exists():
    router.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ai-ui")
