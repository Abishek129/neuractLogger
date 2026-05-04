# mypy: ignore-errors
"""
Conversation History — persistence + sliding window for the Hermes Agent.

Stores the full message log (user + assistant only — tool calls are ephemeral).
Persisted to {session_dir}/chat_history.json.
Implements sliding window to keep context within LLM limits.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("loggerfast.ai.history")

_HISTORY_FILENAME = "chat_history.json"


class ChatHistory:
    """Manages conversation history for the agent loop."""

    MAX_MESSAGES = 50
    MAX_TOOL_RESULT_CHARS = 2000
    TRIM_AFTER_TURNS = 2

    def __init__(self, session_dir: Path):
        self.session_dir = Path(session_dir)
        self.messages: list[dict[str, Any]] = []

    def append(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if len(self.messages) > self.MAX_MESSAGES:
            if self.messages and self.messages[0].get("role") == "system":
                self.messages = [self.messages[0]] + self.messages[-(self.MAX_MESSAGES - 1):]
            else:
                self.messages = self.messages[-self.MAX_MESSAGES:]

    def get_messages(self, max_chars: int = 80000) -> list[dict[str, Any]]:
        """Get messages for the LLM, trimming old tool results to save context."""
        result = []
        total_chars = 0
        n = len(self.messages)

        for i, msg in enumerate(self.messages):
            entry = dict(msg)
            age = n - i

            if entry.get("role") == "tool" and age > self.TRIM_AFTER_TURNS * 3:
                content = entry.get("content", "")
                if len(content) > self.MAX_TOOL_RESULT_CHARS:
                    entry["content"] = content[:self.MAX_TOOL_RESULT_CHARS] + "...[trimmed]"

            entry_size = len(json.dumps(entry, ensure_ascii=False, default=str))
            if total_chars + entry_size > max_chars and i > 0:
                break
            total_chars += entry_size
            result.append(entry)

        return result

    @staticmethod
    def _sanitize_html(text: str) -> str:
        """Strip HTML/script tags from text to prevent stored XSS."""
        import re
        # Remove <script>...</script> blocks entirely
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Strip remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        return text

    def save_turn(self, user_msg: str, assistant_msg: str) -> None:
        """Save a complete turn (user + final assistant response).

        Only user and final response are persisted. Tool calls and tool
        results are NOT saved — they're ephemeral to the current agent
        loop iteration. This prevents history poisoning.
        User messages are sanitized to strip HTML/script tags.
        """
        self.messages.append({"role": "user", "content": self._sanitize_html(user_msg)})
        self.messages.append({"role": "assistant", "content": assistant_msg})
        self.save()

    def save(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self.session_dir / _HISTORY_FILENAME
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.messages, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)

    @classmethod
    def load(cls, session_dir: Path) -> "ChatHistory":
        history = cls(session_dir)
        path = Path(session_dir) / _HISTORY_FILENAME
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    history.messages = data
            except Exception:
                logger.warning("chat_history_load_failed", exc_info=True)
        return history

    def clear(self) -> None:
        self.messages = []

    def __len__(self) -> int:
        return len(self.messages)
