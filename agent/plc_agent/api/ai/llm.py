# mypy: ignore-errors
"""
LLM Configuration — Qwen3.5-27B via Ollama (OpenAI-compatible API).

Environment variables:
    AI_BASE_URL   — LLM API endpoint  (default: http://localhost:11434/v1)
    AI_MODEL      — model name        (default: qwen3.5:27b)
    AI_API_KEY    — API key           (default: ollama)
    AI_MAX_TOKENS — max output tokens (default: 4096)
    AI_EXTRA_BODY — JSON string of extra body params (default: {})

    VISION_AI_ENABLED  — enable GLM-OCR vision model (default: false)
    VISION_AI_MODEL    — vision model name (default: glm-ocr)
    VISION_AI_BASE_URL — vision API endpoint (default: http://localhost:11434/v1)
    VISION_AI_API_KEY  — vision API key (default: ollama)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("loggerfast.ai.llm")


@dataclass
class LLMConfig:
    """Configuration for the primary reasoning model."""

    api_base: str = "http://localhost:8201/v1"
    model: str = "Qwen/Qwen3.5-27B-FP8"
    api_key: str = "ollama"
    max_tokens: int = 4096
    extra_body: Dict[str, Any] = field(default_factory=dict)

    # Vision model (GLM-OCR) — separate endpoint for PDF/image tasks
    vision_enabled: bool = False
    vision_model: Optional[str] = None
    vision_api_base: Optional[str] = None
    vision_api_key: Optional[str] = None

    # Cloud fallback (Phase 3D) — for uncertain device identification
    cloud_enabled: bool = False
    cloud_api_base: str = ""
    cloud_api_key: str = ""
    cloud_model: str = ""
    cloud_max_tokens: int = 2048
    cloud_timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Build config from environment variables with sensible defaults."""
        api_base = os.getenv("AI_BASE_URL", "http://localhost:8201/v1")
        model = os.getenv("AI_MODEL", "Qwen/Qwen3.5-27B-FP8")
        api_key = os.getenv("AI_API_KEY", "none")
        max_tokens = int(os.getenv("AI_MAX_TOKENS", "4096"))

        # Extra body params (e.g. {"chat_template_kwargs": {"enable_thinking": true}})
        extra_body_raw = os.getenv("AI_EXTRA_BODY", "{}")
        try:
            extra_body = json.loads(extra_body_raw)
        except (json.JSONDecodeError, TypeError):
            extra_body = {}

        # Vision model (GLM-OCR via Ollama)
        vision_enabled = os.getenv("VISION_AI_ENABLED", "false").lower() in ("1", "true", "yes")
        vision_model = os.getenv("VISION_AI_MODEL", "glm-ocr") if vision_enabled else None
        vision_api_base = os.getenv("VISION_AI_BASE_URL", "http://localhost:11434/v1") if vision_enabled else None
        vision_api_key = os.getenv("VISION_AI_API_KEY", "ollama") if vision_enabled else None

        # Cloud fallback (Phase 3D)
        cloud_enabled = os.getenv("CLOUD_ENABLED", "false").lower() in ("1", "true", "yes")

        config = cls(
            api_base=api_base,
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            extra_body=extra_body,
            vision_enabled=vision_enabled,
            vision_model=vision_model,
            vision_api_base=vision_api_base,
            vision_api_key=vision_api_key,
            cloud_enabled=cloud_enabled,
            cloud_api_base=os.getenv("CLOUD_API_BASE", ""),
            cloud_api_key=os.getenv("CLOUD_API_KEY", ""),
            cloud_model=os.getenv("CLOUD_MODEL", ""),
            cloud_max_tokens=int(os.getenv("CLOUD_MAX_TOKENS", "2048")),
            cloud_timeout_s=float(os.getenv("CLOUD_TIMEOUT_S", "30.0")),
        )

        logger.info("llm_config_loaded", extra={
            "api_base": api_base,
            "model": model,
            "max_tokens": max_tokens,
            "vision_enabled": vision_enabled,
        })
        return config


# Module-level singleton (lazy)
_config: Optional[LLMConfig] = None


def get_llm_config(force_reload: bool = False) -> LLMConfig:
    """Get the global LLM configuration."""
    global _config
    if _config is None or force_reload:
        _config = LLMConfig.from_env()
    return _config
