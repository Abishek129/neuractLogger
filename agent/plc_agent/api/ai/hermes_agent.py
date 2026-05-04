# mypy: ignore-errors
"""
Hermes Agent — NousResearch hermes-agent wrapper for LoggerFast.

Wraps the AIAgent from hermes-agent with:
- Background thread execution via asyncio.to_thread()
- NDJSON event streaming via CallbackBridge
- Reasoning tag stripping (Qwen <think>...</think>)
- Conversation history persistence (user + assistant only)

Public interface:
    HermesAgent(session)
    async def run(user_message) -> AsyncIterator[dict]
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, AsyncIterator

from .session import AISession, SessionState

logger = logging.getLogger("loggerfast.ai.agent")

# Ensure vendor is on sys.path (same as adapter)
_VENDOR_DIR = str(Path(__file__).resolve().parents[3] / "vendor" / "hermes-agent")
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)


# ---------------------------------------------------------------------------
# NDJSON event helpers
# ---------------------------------------------------------------------------

def _chat_event(event: str, **kw) -> dict:
    return {"event": event, **kw}


def _chat_start(message: str) -> dict:
    return _chat_event("chat_start", message=message)


def _chat_complete(state: str, message: str, **extra) -> dict:
    return _chat_event("chat_complete", session_state=state, message=message, **extra)


# ---------------------------------------------------------------------------
# Reasoning stripper — Qwen 3.5 via Ollama with thinking mode produces:
#   <think>\n...reasoning...\n</think>\n\nActual response
# or:
#   Thinking Process:\n1. ...\n</think>\n\nActual response
# ---------------------------------------------------------------------------

def _strip_reasoning(raw: str) -> str:
    """Extract the user-facing response by removing thinking content."""
    text = raw

    # 1. Split on </think> — the definitive boundary
    if "</think>" in text:
        after = text.rsplit("</think>", 1)[-1].strip()
        if after:
            return after

    # 2. Remove paired <think>...</think> blocks
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"</?think>", "", cleaned).strip()
    if cleaned and cleaned != text.strip():
        return cleaned

    # 3. "Thinking Process:" header — truncated output (no </think>)
    if re.match(r"^Thinking Process:", text, re.IGNORECASE):
        lines = text.split("\n")
        blank_run = 0
        for i, line in enumerate(lines):
            if i == 0:
                continue
            s = line.strip()
            if not s:
                blank_run += 1
                continue
            if (s[0].isdigit() or line.startswith("    ") or line.startswith("\t")
                    or s.startswith("*") or s.startswith("-")):
                blank_run = 0
                continue
            if blank_run >= 1:
                result = "\n".join(lines[i:]).strip()
                if result:
                    return result
            blank_run = 0

    # 4. Strip <result>...</result> blocks and first non-empty line after
    #    (model thinking leaks as first line after tool results)
    cleaned = re.sub(r"<result>.*?</result>", "", text, flags=re.DOTALL).strip()
    if not cleaned:
        return text
    lines = cleaned.split("\n")
    # Drop leading empty lines, then drop first non-empty line (thinking)
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start < len(lines):
        # Skip the thinking line
        rest = "\n".join(lines[start + 1:]).strip()
        if rest:
            return rest
    return cleaned


# ---------------------------------------------------------------------------
# Shared SessionDB singleton (FTS5 session search)
# ---------------------------------------------------------------------------

_shared_session_db = None


def _get_session_db():
    """Lazy-init shared SessionDB for FTS5 cross-session search."""
    global _shared_session_db
    if _shared_session_db is not None:
        return _shared_session_db
    try:
        from hermes_state import SessionDB
        _shared_session_db = SessionDB()
        logger.info("hermes_session_db_initialized")
        return _shared_session_db
    except Exception as exc:
        logger.warning("hermes_session_db_unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Learning signal builder
# ---------------------------------------------------------------------------

def _build_learning_signal(session) -> dict:
    """Build learning signal after a session reaches APPLIED or FAILED.

    Captures: clean_run flag, retry detection, device count, error types,
    abstract patterns. No site-specific data (IPs, device names).
    """
    events = getattr(session, "tool_events", []) or []

    # Detect retries: a tool that produced an error was called again
    errored_tools = set()
    has_retries = False
    for ev in events:
        name = ev.get("tool_name", "")
        if ev.get("error_type"):
            errored_tools.add(name)
        elif name in errored_tools:
            has_retries = True  # tool was retried after an error

    # Detect user corrections: plan was rejected/discarded at least once
    has_corrections = getattr(session, "plan_rejection_count", 0) > 0

    clean_run = not has_retries and not has_corrections

    # Counts from created entities
    entities = getattr(session, "created_entities", {}) or {}
    device_count = len(entities.get("device_ids", []))

    # Error types encountered
    error_types = list({ev["error_type"] for ev in events if ev.get("error_type")})

    # Abstract patterns
    patterns = []
    plan = getattr(session, "staged_plan", None) or {}
    summary = plan.get("summary", {})
    if device_count > 0:
        patterns.append({
            "id": f"batch_{device_count}dev",
            "name": f"batch_{device_count}_devices",
            "description": (
                f"Configured {device_count} devices with "
                f"{summary.get('tables', 0)} tables, "
                f"{summary.get('mappings', 0)} mappings"
            ),
        })

    state_val = getattr(session.state, "value", str(session.state))

    return {
        "valid": state_val == "applied",
        "stage": state_val,
        "no_retries": not has_retries,
        "no_user_corrections": not has_corrections,
        "clean_run": clean_run,
        "device_count": device_count,
        "error_types": error_types,
        "tool_call_count": len(events),
        "patterns": patterns,
    }


# ---------------------------------------------------------------------------
# HermesAgent — main wrapper
# ---------------------------------------------------------------------------

class HermesAgent:
    """NousResearch hermes-agent wrapper for LoggerFast.

    Same public interface as the Neurareport wrapper:
        HermesAgent(session)
        async def run(user_message) -> AsyncIterator[dict]
    """

    MAX_TOOL_ROUNDS = 30
    CONVERSATION_TIMEOUT = 1800  # 30 minutes

    def __init__(self, session: AISession):
        self.session = session
        self._ndjson_queue: asyncio.Queue[dict] = asyncio.Queue()

    def _persist_learning_signal(self) -> None:
        """Build and persist learning signal after APPLIED or FAILED."""
        try:
            signal = _build_learning_signal(self.session)
            self.session.learning_signal = signal
            signal_path = self.session.session_dir / "learning_signal.json"
            signal_path.write_text(
                json.dumps(signal, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("learning_signal_persisted", extra={
                "session_id": self.session.session_id,
                "clean_run": signal.get("clean_run"),
                "device_count": signal.get("device_count"),
            })
        except Exception:
            logger.debug("learning_signal_failed", exc_info=True)

    def _save_trajectory(self, history) -> None:
        """Write session trajectory in ShareGPT format."""
        try:
            messages = []
            for msg in history.messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    messages.append({"from": "human", "value": content})
                elif role == "assistant":
                    messages.append({"from": "gpt", "value": content})

            if not messages:
                return

            entry = {
                "conversations": messages,
                "session_id": self.session.session_id,
                "completed": self.session.state == SessionState.APPLIED,
                "learning_signal": self.session.learning_signal,
                "timestamp": self.session.updated_at,
            }

            traj_path = self.session.session_dir / "trajectory.jsonl"
            with open(traj_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

            logger.info("trajectory_saved", extra={
                "session_id": self.session.session_id,
                "path": str(traj_path),
            })

            # Also append to global trajectory files for bulk collection
            try:
                global_dir = Path(__file__).resolve().parents[3] / "data" / "ai_sessions"
                global_dir.mkdir(parents=True, exist_ok=True)
                if entry.get("completed"):
                    global_path = global_dir / "trajectory_samples.jsonl"
                else:
                    global_path = global_dir / "failed_trajectories.jsonl"
                with open(global_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            except Exception:
                logger.debug("global_trajectory_save_failed", exc_info=True)

        except Exception:
            logger.debug("trajectory_save_failed", exc_info=True)

    def _extract_training_data(self) -> None:
        """Extract confirmed-good readings from clean_run for anomaly training."""
        try:
            signal = self.session.learning_signal or {}
            if not signal.get("clean_run"):
                return

            readings = getattr(self.session, "captured_readings", []) or []
            if not readings:
                return

            from .validation.training_data import append_training_samples
            from .validation.anomaly import _sanitize_key
            from .mfm_kb.manager import KBManager

            mgr = KBManager.instance()

            # Group readings by model
            by_model: dict[str, list] = {}
            for r in readings:
                model = r.get("model")
                if not model:
                    continue
                key = _sanitize_key(model)
                by_model.setdefault(key, []).append(r)

            for model_family, model_readings in by_model.items():
                kb_entry = mgr.get_entry(model_family)
                if kb_entry is None:
                    continue
                regs = kb_entry.registers
                kb_regs = [r.model_dump() if hasattr(r, "model_dump") else r for r in regs]
                count = append_training_samples(model_family, model_readings, kb_regs)
                if count > 0:
                    logger.info("training_data_extracted", extra={
                        "session_id": self.session.session_id,
                        "model": model_family,
                        "samples": count,
                    })
        except Exception:
            logger.debug("training_data_extraction_failed", exc_info=True)

    def _record_marketplace_outcomes(self, success: bool) -> None:
        """Record skill usage outcomes in the marketplace (Phase 3D)."""
        try:
            from .marketplace import SkillMarketplace
            mp = SkillMarketplace.instance()

            # Extract skill names used from tool events
            events = getattr(self.session, "tool_events", []) or []
            skills_used: set[str] = set()
            for ev in events:
                # Hermes skill tools record skill name in args
                if ev.get("tool_name") in ("skill_view", "skill_manage"):
                    args = ev.get("args", {})
                    name = args.get("skill_name") or args.get("name", "")
                    if name:
                        skills_used.add(name)

            for skill_name in skills_used:
                mp.record_outcome(skill_name, success=success)

            if skills_used:
                logger.info("marketplace_outcomes_recorded", extra={
                    "session_id": self.session.session_id,
                    "skills": list(skills_used),
                    "success": success,
                })
        except ImportError:
            pass
        except Exception:
            logger.debug("marketplace_outcome_failed", exc_info=True)

    async def run(self, user_message: str) -> AsyncIterator[dict]:
        """Main entry point. Yields NDJSON events."""
        # Lazy imports — avoid import-time side effects from hermes-agent
        from run_agent import AIAgent
        from .hermes_adapter import (
            _current_ctx,
            register_loggerfast_tools,
            get_toolset_for_state,
            CallbackBridge,
        )
        from .chat_history import ChatHistory
        from .llm import get_llm_config
        from .system_prompt import build_system_prompt
        from .tools import ToolContext

        # 0. Reset per-turn iteration counter
        self.session.reset_iteration_count()

        # 1. Build ToolContext
        ctx = ToolContext(
            session=self.session,
            event_queue=self._ndjson_queue,
            tool_call_counts=self.session.tool_call_counts,
        )

        # 2. Set context var (copied to Hermes thread by asyncio.to_thread)
        _current_ctx.set(ctx)

        # 3. Register tools once per process
        loop = asyncio.get_running_loop()
        register_loggerfast_tools(loop)

        # 4. Build callback bridge
        bridge = CallbackBridge(self._ndjson_queue, loop)

        # 5. LLM config
        llm = get_llm_config()

        # 6. Create AIAgent
        agent = AIAgent(
            base_url=llm.api_base,
            api_key=llm.api_key,
            model=llm.model,
            max_tokens=llm.max_tokens,
            extra_body_override=llm.extra_body,

            # Agent behavior
            quiet_mode=True,
            ephemeral_system_prompt=build_system_prompt(self.session),
            max_iterations=self.MAX_TOOL_ROUNDS,
            platform="api",

            # Tool filtering — state-specific toolset
            # Use 'chatting' toolset for created/discarded/applied states
            # since hermes_agent.run() transitions them to chatting before the LLM runs
            enabled_toolsets=[get_toolset_for_state(
                "chatting" if self.session.state.value in ("created", "discarded", "applied")
                else self.session.state.value
            )],

            # Persistent learning (Phase 2A)
            save_trajectories=True,
            skip_context_files=True,
            skip_memory=False,         # Enable memory (MEMORY.md + USER.md)
            persist_session=True,      # Persist to SessionDB for session_search

            # Session linkage
            session_id=self.session.session_id,
            session_db=_get_session_db(),  # Shared FTS5 DB for session_search

            # Crash recovery
            checkpoints_enabled=True,

            # Callbacks → NDJSON events
            tool_start_callback=bridge.on_tool_start,
            tool_complete_callback=bridge.on_tool_complete,
            tool_progress_callback=bridge.on_tool_progress,
            thinking_callback=bridge.on_thinking,
            status_callback=bridge.on_status,
            step_callback=bridge.on_step,
            clarify_callback=bridge.on_clarify,
        )

        # 6b. Cap memory sizes to avoid context bloat
        if hasattr(agent, '_memory_store') and agent._memory_store:
            agent._memory_store.memory_char_limit = min(
                agent._memory_store.memory_char_limit, 1500)
            agent._memory_store.user_char_limit = min(
                agent._memory_store.user_char_limit, 1000)

        # 7. Load conversation history
        history = ChatHistory.load(self.session.session_dir)
        conversation_history = history.get_messages()

        # 8. Transition to CHATTING if not already there
        #    Handles: CREATED, FAILED (with recovery context), DISCARDED, APPLIED
        recovery_prefix = ""
        if self.session.state == SessionState.FAILED:
            recovery = self.session.get_recovery_context()
            if recovery:
                cp = recovery.get("checkpoint") or {}
                entities = recovery.get("created_entities") or {}
                parts = []
                parts.append("[RECOVERY CONTEXT — Session failed during execution]")
                if cp.get("last_tool"):
                    parts.append(f"Last tool: {cp['last_tool']}")
                if cp.get("error"):
                    parts.append(f"Error: {cp['error'][:200]}")
                entity_summary = {k: len(v) for k, v in entities.items() if v}
                if entity_summary:
                    parts.append(f"Entities already created: {entity_summary}")
                if recovery.get("staged_plan"):
                    parts.append(f"Original plan: {json.dumps(recovery['staged_plan'].get('summary', {}))}")
                recovery_prefix = "\n".join(parts) + "\n\n"
            self.session.transition(SessionState.CHATTING)
        elif self.session.state in (
            SessionState.CREATED, SessionState.DISCARDED, SessionState.APPLIED,
        ):
            self.session.transition(SessionState.CHATTING)

        # 9. Yield chat_start
        yield _chat_start(message="Processing your request...")

        # 10. Run Hermes in background thread, drain NDJSON events
        SENTINEL = object()

        async def _run_hermes():
            try:
                effective_message = recovery_prefix + user_message if recovery_prefix else user_message
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        agent.run_conversation,
                        effective_message,
                        conversation_history=conversation_history,
                    ),
                    timeout=self.CONVERSATION_TIMEOUT,
                )
                return result
            except asyncio.TimeoutError:
                logger.warning("hermes_conversation_timeout", extra={
                    "timeout": self.CONVERSATION_TIMEOUT,
                    "session_id": self.session.session_id,
                })
                return {
                    "final_response": (
                        f"The operation timed out after {self.CONVERSATION_TIMEOUT}s. "
                        "Please try again or simplify your request."
                    ),
                }
            finally:
                loop.call_soon_threadsafe(self._ndjson_queue.put_nowait, SENTINEL)

        hermes_task = asyncio.create_task(_run_hermes())

        # Drain NDJSON events as they arrive
        while True:
            event = await self._ndjson_queue.get()
            if event is SENTINEL:
                break
            yield event

        # 11. Get final response
        try:
            hermes_result = await hermes_task
            final_response = hermes_result.get("final_response", "") or ""
        except Exception as exc:
            logger.exception("hermes_agent_failed", extra={
                "session_id": self.session.session_id,
            })
            # If we were applying, transition to FAILED
            if self.session.state == SessionState.APPLYING:
                try:
                    self.session.transition(SessionState.FAILED)
                    self._persist_learning_signal()
                    self._record_marketplace_outcomes(success=False)
                    self.session.save()
                except Exception:
                    pass
            yield _chat_complete(
                state=self.session.state.value,
                message=f"Agent failed: {exc}",
            )
            return

        # 11.5. If we were APPLYING and completed successfully → APPLIED
        if self.session.state == SessionState.APPLYING:
            try:
                self.session.transition(SessionState.APPLIED)
                self._persist_learning_signal()
                self._extract_training_data()
                self._record_marketplace_outcomes(success=True)
                self.session.save()
            except Exception:
                logger.debug("applied_transition_failed", exc_info=True)

        # 11.7. Flush memories to disk
        try:
            await asyncio.to_thread(agent.flush_memories)
        except Exception:
            logger.debug("flush_memories_failed", exc_info=True)

        # 12. Strip thinking tags
        clean_content = _strip_reasoning(final_response)

        # 13. Save turn (user + assistant only — no tool calls)
        #     Skip persisting if assistant response is empty (LLM failure)
        if clean_content:
            history.save_turn(user_message, clean_content)
        else:
            logger.warning("empty_assistant_response_not_saved", extra={
                "session_id": self.session.session_id,
            })
        self.session.record_turn()
        self.session.save()

        # 13.5. Save trajectory for APPLIED/FAILED sessions
        if self.session.state in (SessionState.APPLIED, SessionState.FAILED):
            self._save_trajectory(history)

        # 14. Yield chat_complete
        yield _chat_complete(
            state=self.session.state.value,
            message=clean_content,
        )
