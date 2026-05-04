# mypy: ignore-errors
"""
Hermes Adapter — bridges LoggerFast async tools to NousResearch hermes-agent.

This module:
1. Registers LoggerFast tools into Hermes's ToolRegistry
2. Wraps async tool handlers into sync handlers (Hermes requirement)
3. Provides CallbackBridge mapping Hermes callbacks → NDJSON events
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Ensure vendor/hermes-agent is on sys.path
_VENDOR_DIR = str(Path(__file__).resolve().parents[3] / "vendor" / "hermes-agent")
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)

from .tools import (
    TOOL_DISPATCH, TOOL_SCHEMAS, TOOL_CALL_LIMITS, ToolContext,
    PreconditionError, CallLimitExceeded, get_effective_limit,
    _sanitize_for_agent, _classify_error,
)

logger = logging.getLogger("loggerfast.ai.adapter")

# ---------------------------------------------------------------------------
# Context var for passing ToolContext to sync handlers
# asyncio.to_thread() copies context vars to the new thread, so
# Hermes's sync handler closures can read the current ToolContext.
# ---------------------------------------------------------------------------

_current_ctx: contextvars.ContextVar[ToolContext] = contextvars.ContextVar(
    "loggerfast_tool_ctx"
)

# ---------------------------------------------------------------------------
# Tool timeout (seconds) — read-only tools are fast
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 60

# Per-tool timeout overrides (seconds) — network and heavy tools need more time
_TOOL_TIMEOUTS: dict[str, int] = {
    "ping_host": 120,
    "scan_port": 120,
    "browse_opcua_nodes": 120,
    "read_raw_registers": 120,
    "create_gateway": 120,
    "test_device": 120,
    "run_anomaly_check": 90,
    # Phase 2B — discovery (long-running network operations)
    "scan_subnet": 300,
    "enumerate_unit_ids": 180,
    "identify_device": 180,
    "discover_and_identify": 600,
    "retrain_anomaly_model": 120,
    # Phase 3B — temporal model training
    "train_temporal_model": 120,
    "retrain_temporal_model": 120,
    # Phase 3D
    "infer_topology": 120,
    "cloud_identify": 60,
    # Phase 4 — manage/mutate
    "connect_device": 120,
    "stop_job": 30,
    "pause_job": 30,
    "delete_job": 30,
}

# Tool tier map for trace classification
_TOOL_TIERS: dict[str, str] = {
    "read_config": "read", "read_gateway_list": "read", "read_schema_list": "read",
    "read_table_mapping": "read", "read_job_status": "read",
    "read_device_status": "read", "read_source_file": "read",
    "read_live_values": "read", "validate_live_readings": "diagnostic",
    "run_anomaly_check": "diagnostic",
    "ping_host": "diagnostic", "scan_port": "diagnostic",
    "read_raw_registers": "diagnostic", "browse_opcua_nodes": "diagnostic",
    "query_db": "diagnostic", "test_device": "diagnostic",
    "propose_plan": "write",
    "create_gateway": "write", "create_device": "write",
    "create_schema": "write", "create_table": "write",
    "apply_mappings": "write", "migrate_table": "write",
    "create_job": "write", "start_job": "write",
    "list_mfm_models": "kb", "lookup_mfm_model": "kb",
    "read_document": "kb", "read_document_page_image": "kb",
    "read_mfm_document": "kb", "search_mfm_document": "kb",
    "propose_kb_entry": "kb", "update_kb_entry": "kb",
    # Phase 2B — discovery
    "scan_subnet": "diagnostic", "enumerate_unit_ids": "diagnostic",
    "identify_device": "diagnostic", "discover_and_identify": "diagnostic",
    "retrain_anomaly_model": "diagnostic",
    "read_prediction_status": "diagnostic",
    # Phase 3B — temporal
    "read_temporal_status": "diagnostic",
    "train_temporal_model": "diagnostic",
    "retrain_temporal_model": "diagnostic",
    # Phase 3D — advanced
    "infer_topology": "diagnostic",
    "read_topology": "read",
    "cloud_identify": "diagnostic",
    "marketplace_search": "read",
    "marketplace_publish": "write",
    "create_session_group": "write",
    # Phase 4 — manage/mutate
    "update_gateway": "write", "delete_gateway": "write",
    "update_device": "write", "delete_device": "write",
    "connect_device": "diagnostic", "disconnect_device": "diagnostic",
    "delete_schema": "write", "add_schema_field": "write", "delete_schema_field": "write",
    "update_table": "write", "delete_table": "write",
    "bind_device_to_table": "write", "unbind_device_from_table": "write",
    "delete_mapping_row": "write", "copy_mappings": "write",
    "stop_job": "diagnostic", "pause_job": "diagnostic", "delete_job": "write",
    "add_db_target": "write", "update_db_target": "write",
    "delete_db_target": "write", "set_default_db_target": "write",
}

_MAX_TOOL_ROUNDS = 30  # must match HermesAgent.MAX_TOOL_ROUNDS

# Hermes native toolsets — included in every state via "includes"
_HERMES_NATIVE_TOOLSETS = [
    "memory", "skills", "todo", "clarify", "session_search",
]

# Hermes-internal tools — styled differently in NDJSON events (not pipeline stages)
_HERMES_INTERNAL_TOOLS = frozenset({
    "memory", "todo", "skills_list", "skill_view", "skill_manage",
    "session_search", "clarify", "delegate_task",
})


# ---------------------------------------------------------------------------
# Sync handler wrapper
# ---------------------------------------------------------------------------

def make_sync_handler(
    tool_name: str,
    tool_fn: Callable,
    event_loop: asyncio.AbstractEventLoop,
) -> Callable:
    """Wrap an async LoggerFast tool for Hermes's sync registry."""

    def handler(args: dict, **kwargs) -> str:
        ctx = _current_ctx.get()
        future = None
        timeout = _TOOL_TIMEOUTS.get(tool_name, _DEFAULT_TIMEOUT)
        t0 = _time.perf_counter()

        # Per-tool call limit check (enforced by adapter, not system prompt)
        limit = get_effective_limit(tool_name, ctx.session)
        if limit is not None:
            count = ctx.tool_call_counts.get(tool_name, 0)
            if count >= limit:
                return json.dumps({
                    "error": "call_limit_exceeded",
                    "tool": tool_name,
                    "limit": limit,
                    "message": f"Tool '{tool_name}' has reached its limit of {limit} calls this session.",
                })
            ctx.tool_call_counts[tool_name] = count + 1

        try:
            future = asyncio.run_coroutine_threadsafe(
                tool_fn(ctx, **args), event_loop
            )
            raw_result = future.result(timeout=timeout)

        except PreconditionError as e:
            logger.warning("tool_precondition_failed", extra={"tool": tool_name})
            raw_result = {
                "error": "precondition_failed",
                "tool": tool_name,
                "message": str(e),
            }
        except CallLimitExceeded as e:
            logger.warning("tool_call_limit_exceeded", extra={"tool": tool_name})
            raw_result = {
                "error": "call_limit_exceeded",
                "tool": tool_name,
                "message": str(e),
            }
        except TimeoutError:
            if future is not None:
                future.cancel()
            logger.warning("tool_timeout", extra={"tool": tool_name, "timeout": timeout})
            raw_result = {
                "error": "tool_timeout",
                "tool": tool_name,
                "timeout_seconds": timeout,
                "message": f"Tool '{tool_name}' timed out after {timeout}s.",
            }
        except Exception as e:
            logger.exception("tool_execution_failed", extra={"tool": tool_name})
            raw_result = {
                "error": "tool_execution_failed",
                "tool": tool_name,
                "message": str(e),
            }

        duration_ms = int((_time.perf_counter() - t0) * 1000)

        # ── CAPTURE READINGS FOR TRAINING (Phase 2C) ──
        _CAPTURE_TOOLS = {"run_anomaly_check", "read_live_values", "validate_live_readings"}
        if tool_name in _CAPTURE_TOOLS:
            try:
                if isinstance(raw_result, dict) and not raw_result.get("error"):
                    values = (raw_result.get("values")
                              or raw_result.get("readings")
                              or None)
                    if values and isinstance(values, dict):
                        ctx.session.captured_readings.append({
                            "model": args.get("model", ""),
                            "values": values,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
            except Exception:
                pass

        # ── SANITIZATION GATE ──
        if isinstance(raw_result, dict):
            sanitized = _sanitize_for_agent(tool_name, raw_result, args)
        else:
            sanitized = raw_result

        # ── TRACE RECORDING ──
        error_type = _classify_error(tool_name, raw_result) if isinstance(raw_result, dict) else None
        try:
            safe_args = {k: v for k, v in args.items()
                         if k not in ("password", "credentials", "secret", "pass")}
            result_preview = json.dumps(sanitized, default=str)[:200] if isinstance(sanitized, dict) else str(sanitized)[:200]
            ctx.session.record_tool_event({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool_name": tool_name,
                "args": safe_args,
                "result_summary": result_preview,
                "error_type": error_type,
                "duration_ms": duration_ms,
                "tier": _TOOL_TIERS.get(tool_name, "read"),
            })
        except Exception:
            pass

        # ── BUDGET PRESSURE WARNING ──
        if isinstance(sanitized, dict):
            used = ctx.session.iteration_count
            pct = (used / _MAX_TOOL_ROUNDS) * 100 if _MAX_TOOL_ROUNDS > 0 else 0
            if pct >= 90:
                sanitized["_budget_warning"] = (
                    f"Near iteration limit ({int(pct)}%). "
                    "Prioritize essential operations only."
                )
            elif pct >= 70:
                sanitized["_budget_warning"] = (
                    f"Approaching iteration budget ({int(pct)}%). "
                    "Consider batching remaining operations."
                )

        result_str = json.dumps(sanitized, ensure_ascii=False, default=str)
        if len(result_str) > 8000:
            result_str = result_str[:8000] + '..."truncated"}'

        return result_str

    return handler


# ---------------------------------------------------------------------------
# Tool Registration — called once per process
# ---------------------------------------------------------------------------

_registered = False


def register_loggerfast_tools(event_loop: asyncio.AbstractEventLoop) -> None:
    """Register LoggerFast tools into Hermes's ToolRegistry + define toolset."""
    global _registered
    if _registered:
        return

    from tools.registry import registry
    from toolsets import TOOLSETS

    # Build schema lookup: tool_name → schema dict
    schema_map: dict[str, dict] = {}
    for entry in TOOL_SCHEMAS:
        fn_schema = entry.get("function", {})
        name = fn_schema.get("name")
        if name:
            schema_map[name] = fn_schema

    # Register each tool
    for tool_name, tool_fn in TOOL_DISPATCH.items():
        schema = schema_map.get(tool_name, {
            "name": tool_name,
            "description": f"LoggerFast tool: {tool_name}",
            "parameters": {"type": "object", "properties": {}, "required": []},
        })
        handler = make_sync_handler(tool_name, tool_fn, event_loop)

        registry.register(
            name=tool_name,
            toolset="loggerfast",
            schema=schema,
            handler=handler,
            check_fn=lambda: True,
            is_async=False,
        )

    # Define the full "loggerfast" toolset (fallback — all tools)
    all_tool_names = sorted(TOOL_DISPATCH.keys())
    TOOLSETS["loggerfast"] = {
        "tools": all_tool_names,
        "includes": list(_HERMES_NATIVE_TOOLSETS),
    }

    # State-specific toolsets — smaller tool sets per session state
    # reduces LLM context size and guides tool selection.
    # Read-only tools are always available; write tools gated by state.
    _READ_TOOLS = {
        "read_config", "read_gateway_list", "read_schema_list",
        "read_table_mapping", "read_job_status", "read_device_status",
        "read_source_file",
        # Phase 3D — read-only advanced
        "read_topology", "marketplace_search",
    }
    _DIAGNOSTIC_TOOLS = {
        "ping_host", "scan_port", "read_raw_registers",
        "browse_opcua_nodes", "query_db",
        # Phase 2B — discovery
        "scan_subnet", "enumerate_unit_ids", "identify_device",
        "discover_and_identify",
        # Phase 3D — diagnostic advanced
        "infer_topology", "cloud_identify",
    }
    _LIVE_TOOLS = {
        "read_live_values", "validate_live_readings", "run_anomaly_check",
        "read_prediction_status", "read_temporal_status",
    }
    _RETRAIN_TOOLS = {"retrain_anomaly_model", "train_temporal_model", "retrain_temporal_model"}
    _KB_READ_TOOLS = {
        "list_mfm_models", "lookup_mfm_model", "read_document",
        "read_document_page_image", "read_mfm_document", "search_mfm_document",
    }
    _KB_WRITE_TOOLS = {"propose_kb_entry", "update_kb_entry"}
    _WRITE_TOOLS = {
        "create_gateway", "create_device", "create_schema",
        "create_table", "apply_mappings", "migrate_table",
        "create_job", "start_job",
        # Phase 3D — write advanced
        "marketplace_publish", "create_session_group",
    }
    _PLAN_TOOLS = {"propose_plan"}
    _TEST_TOOLS = {"test_device"}

    # Phase 4 — manage/mutate tool sets
    _MANAGE_TOOLS = {
        "update_gateway", "delete_gateway",
        "update_device", "delete_device", "connect_device", "disconnect_device",
        "delete_schema", "add_schema_field", "delete_schema_field",
        "update_table", "delete_table", "bind_device_to_table", "unbind_device_from_table",
        "delete_mapping_row", "copy_mappings",
        "stop_job", "pause_job", "delete_job",
        "add_db_target", "update_db_target", "delete_db_target", "set_default_db_target",
    }
    # Subset available in CHATTING (no plan required) — operational + destructive
    _CHATTING_MANAGE_TOOLS = {
        "delete_gateway", "delete_device", "connect_device", "disconnect_device",
        "delete_schema", "delete_schema_field",
        "delete_table", "unbind_device_from_table",
        "delete_mapping_row",
        "stop_job", "pause_job", "delete_job",
        "delete_db_target",
    }

    STATE_TOOLS: dict[str, set[str]] = {
        "created":          _READ_TOOLS,
        "chatting":         _READ_TOOLS | _DIAGNOSTIC_TOOLS | _LIVE_TOOLS | _RETRAIN_TOOLS | _KB_READ_TOOLS | _PLAN_TOOLS | _TEST_TOOLS | _CHATTING_MANAGE_TOOLS,
        "plan_proposed":    _READ_TOOLS | _LIVE_TOOLS | _KB_READ_TOOLS,
        "awaiting_review":  _READ_TOOLS | _LIVE_TOOLS | _KB_READ_TOOLS,
        "approved":         _READ_TOOLS | _LIVE_TOOLS | _WRITE_TOOLS | _KB_WRITE_TOOLS | _TEST_TOOLS | _MANAGE_TOOLS,
        "applying":         _READ_TOOLS | _LIVE_TOOLS | _WRITE_TOOLS | _KB_WRITE_TOOLS | _TEST_TOOLS | _MANAGE_TOOLS,
        "applied":          _READ_TOOLS | _LIVE_TOOLS | _RETRAIN_TOOLS | _DIAGNOSTIC_TOOLS | _KB_READ_TOOLS | _TEST_TOOLS | _CHATTING_MANAGE_TOOLS,
        "failed":           _READ_TOOLS | _DIAGNOSTIC_TOOLS | _LIVE_TOOLS | _CHATTING_MANAGE_TOOLS,
        "discarded":        _READ_TOOLS | _CHATTING_MANAGE_TOOLS,
    }

    # Register state-specific toolsets in TOOLSETS dict
    for state, tool_names in STATE_TOOLS.items():
        toolset_name = f"lf_{state}"
        # Only include tools that actually exist in TOOL_DISPATCH
        valid_tools = sorted(tool_names & set(all_tool_names))
        TOOLSETS[toolset_name] = {
            "tools": valid_tools,
            "includes": list(_HERMES_NATIVE_TOOLSETS),
        }
        logger.debug("state_toolset_defined", extra={
            "state": state, "toolset": toolset_name, "count": len(valid_tools),
        })

    _registered = True
    logger.info("loggerfast_tools_registered", extra={
        "count": len(TOOL_DISPATCH),
        "states": list(STATE_TOOLS.keys()),
    })


def get_toolset_for_state(state: str) -> str:
    """Return the toolset name for a given session state.

    Maps state "chatting" → "lf_chatting". Falls back to "loggerfast" (all tools)
    for unknown states.
    """
    return f"lf_{state}" if f"lf_{state}" in _get_known_state_toolsets() else "loggerfast"


def _get_known_state_toolsets() -> set[str]:
    """Return set of state toolset names that were registered."""
    try:
        from toolsets import TOOLSETS
        return {k for k in TOOLSETS if k.startswith("lf_")}
    except ImportError:
        return set()


# ---------------------------------------------------------------------------
# Callback Bridge — maps Hermes AIAgent callbacks → NDJSON events
# ---------------------------------------------------------------------------

class CallbackBridge:
    """Maps Hermes AIAgent callbacks → NDJSON events for the frontend.

    Hermes fires callbacks from its sync thread. We use
    loop.call_soon_threadsafe() to push events into the async NDJSON queue.

    Callback signatures (from hermes-agent run_agent.py):
        tool_start_callback(tc_id: str, name: str, args: dict)
        tool_complete_callback(tc_id: str, name: str, args: dict, result: str)
        tool_progress_callback(name: str, preview: str, args: dict)
        stream_delta_callback(delta: str)
        thinking_callback(text: str)
        status_callback(type_: str, message: str)
    """

    # Write tools that should trigger checkpoint saves during APPLYING
    _CHECKPOINT_TOOLS = {
        "create_gateway", "create_device", "create_schema", "create_table",
        "apply_mappings", "migrate_table", "create_job", "start_job",
        "propose_kb_entry", "update_kb_entry",
    }

    def __init__(
        self,
        ndjson_queue: asyncio.Queue,
        event_loop: asyncio.AbstractEventLoop,
    ):
        self._queue = ndjson_queue
        self._loop = event_loop

    def _push(self, event: dict) -> None:
        """Thread-safe push to the async NDJSON queue."""
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    # -- Hermes Callbacks --

    def on_tool_start(self, tc_id: str, name: str, args: dict) -> None:
        is_internal = name in _HERMES_INTERNAL_TOOLS
        logger.info("tool_start", extra={"tool": name, "tc_id": tc_id, "internal": is_internal})
        self._push({
            "event": "stage",
            "stage": name,
            "status": "running" if is_internal else "started",
            "progress": 0,
            "internal": is_internal,
        })

    def on_tool_complete(self, tc_id: str, name: str, args: dict, result: str) -> None:
        is_internal = name in _HERMES_INTERNAL_TOOLS
        logger.info("tool_complete", extra={
            "tool": name, "tc_id": tc_id,
            "result_len": len(result) if isinstance(result, str) else 0,
        })
        self._push({
            "event": "stage",
            "stage": name,
            "status": "complete",
            "progress": 100,
            "internal": is_internal,
        })

        # Save checkpoint for write tools during APPLYING (for failure recovery)
        if name in self._CHECKPOINT_TOOLS:
            try:
                ctx = _current_ctx.get()
                from .session import SessionState
                if ctx.session.state == SessionState.APPLYING:
                    error = None
                    if isinstance(result, str) and '"error"' in result:
                        error = result[:500]
                    ctx.session.save_checkpoint(name, args, error)
                    ctx.session.save()
            except Exception:
                logger.debug("checkpoint_save_failed", exc_info=True)

    def on_tool_progress(self, name: str, preview: str, args: dict) -> None:
        self._push({
            "event": "stage",
            "stage": name,
            "status": "running",
            "progress": 50,
        })

    def on_thinking(self, text: str) -> None:
        # Discard reasoning output — stripped from final response
        pass

    def on_stream_delta(self, delta: str) -> None:
        # Not used — we don't stream tokens to frontend
        pass

    def on_status(self, type_: str, message: str) -> None:
        # Internal Hermes lifecycle — not exposed
        logger.debug("hermes_status", extra={"type": type_, "message": message})

    def on_step(self, *args, **kwargs) -> None:
        """Fires after each complete LLM turn."""
        self._push({
            "event": "stage",
            "stage": "agent_turn",
            "status": "complete",
            "progress": 50,
        })

    def on_clarify(self, question: str, choices: list | None = None) -> str:
        """Route clarification request back to user via NDJSON.

        In embedded API mode we can't block for user input. Return the
        question as text — Hermes includes it in its response, user
        answers in the next message.
        """
        self._push({
            "event": "stage",
            "stage": "clarify",
            "status": "waiting",
            "progress": 0,
            "detail": {"question": question, "choices": choices},
        })
        answer = f"I need clarification: {question}"
        if choices:
            answer += f"\nOptions: {', '.join(str(c) for c in choices)}"
        return answer
