# mypy: ignore-errors
"""Phase 3D — Cloud Fallback for uncertain device identification.

When local Qwen can't resolve a device (confidence < 70%), escalate to a
cloud model (Claude / Qwen cloud) via the OpenAI-compatible API.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("loggerfast.ai.cloud_fallback")


@dataclass
class CloudConfig:
    """Configuration for the cloud fallback LLM."""

    enabled: bool = False
    api_base: str = ""
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 2048
    timeout_s: float = 30.0
    max_retries: int = 2
    max_calls_per_session: int = 5

    @classmethod
    def from_env(cls) -> "CloudConfig":
        enabled = os.getenv("CLOUD_ENABLED", "false").lower() in ("1", "true", "yes")
        return cls(
            enabled=enabled,
            api_base=os.getenv("CLOUD_API_BASE", ""),
            api_key=os.getenv("CLOUD_API_KEY", ""),
            model=os.getenv("CLOUD_MODEL", ""),
            max_tokens=int(os.getenv("CLOUD_MAX_TOKENS", "2048")),
            timeout_s=float(os.getenv("CLOUD_TIMEOUT_S", "30.0")),
            max_retries=int(os.getenv("CLOUD_MAX_RETRIES", "2")),
            max_calls_per_session=int(os.getenv("CLOUD_MAX_CALLS", "5")),
        )


# Module-level singleton
_config: Optional[CloudConfig] = None


def get_cloud_config(force_reload: bool = False) -> CloudConfig:
    global _config
    if _config is None or force_reload:
        _config = CloudConfig.from_env()
    return _config


class CloudFallbackClient:
    """OpenAI-compatible client for uncertain device identification."""

    def __init__(self, config: Optional[CloudConfig] = None) -> None:
        self._config = config or get_cloud_config()
        self._call_count = 0

    def is_available(self) -> bool:
        """Check if cloud fallback is enabled and under rate limit."""
        return (
            self._config.enabled
            and bool(self._config.api_base)
            and bool(self._config.api_key)
            and self._call_count < self._config.max_calls_per_session
        )

    def remaining_calls(self) -> int:
        return max(0, self._config.max_calls_per_session - self._call_count)

    async def identify_device(
        self,
        register_data: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        kb_models: List[str],
    ) -> Dict[str, Any]:
        """Ask cloud model to disambiguate device identification.

        Parameters
        ----------
        register_data
            Raw register values (anonymised — no IPs).
        candidates
            Candidate matches with scores from local identification.
        kb_models
            Available KB model names for context.

        Returns
        -------
        Dict with: model, confidence, reasoning, byte_order.
        """
        if not self.is_available():
            return {
                "error": "CLOUD_UNAVAILABLE",
                "message": "Cloud fallback not configured or rate limit reached.",
            }

        prompt = self._build_identification_prompt(register_data, candidates, kb_models)

        try:
            result = await self._call_api(prompt)
            self._call_count += 1
            return self._parse_identification_response(result)
        except Exception as e:
            logger.warning("cloud_identify_failed: %s", e)
            return {"error": "CLOUD_CALL_FAILED", "message": str(e)}

    async def resolve_anomaly(
        self,
        anomaly_result: Dict[str, Any],
        device_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Ask cloud model to explain an anomaly the local model can't resolve."""
        if not self.is_available():
            return {
                "error": "CLOUD_UNAVAILABLE",
                "message": "Cloud fallback not configured or rate limit reached.",
            }

        prompt = self._build_anomaly_prompt(anomaly_result, device_context)

        try:
            result = await self._call_api(prompt)
            self._call_count += 1
            return self._parse_anomaly_response(result)
        except Exception as e:
            logger.warning("cloud_resolve_anomaly_failed: %s", e)
            return {"error": "CLOUD_CALL_FAILED", "message": str(e)}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call_api(self, prompt: str) -> str:
        """Make an OpenAI-compatible chat completion call."""
        import httpx

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        # Support both OpenAI and Anthropic-style endpoints
        url = f"{self._config.api_base.rstrip('/')}/chat/completions"
        payload = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "messages": [
                {"role": "system", "content": _SYSTEM_MSG},
                {"role": "user", "content": prompt},
            ],
        }

        async with httpx.AsyncClient(timeout=self._config.timeout_s) as client:
            for attempt in range(self._config.max_retries + 1):
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < self._config.max_retries:
                        import asyncio
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise
                except (httpx.TimeoutException, httpx.ConnectError):
                    if attempt < self._config.max_retries:
                        import asyncio
                        await asyncio.sleep(1)
                        continue
                    raise

        raise RuntimeError("Cloud API call exhausted retries")

    def _build_identification_prompt(
        self,
        register_data: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        kb_models: List[str],
    ) -> str:
        # Sanitise — strip any IP addresses from register data keys
        safe_data = {
            k: v for k, v in register_data.items()
            if not _looks_like_ip(str(k)) and not _looks_like_ip(str(v))
        }
        return (
            "I have a Modbus device that I cannot confidently identify. "
            "Here is the data:\n\n"
            f"**Register values:**\n```json\n{json.dumps(safe_data, indent=2)}\n```\n\n"
            f"**Local candidate matches:**\n```json\n{json.dumps(candidates, indent=2, default=str)}\n```\n\n"
            f"**Known models in our KB:** {', '.join(kb_models)}\n\n"
            "Based on the register values and candidate scores, which model is this most likely? "
            "Respond with JSON: {\"model\": \"...\", \"confidence\": 0.0-1.0, "
            "\"reasoning\": \"...\", \"byte_order\": \"big_endian|mid_endian|little_endian\"}"
        )

    def _build_anomaly_prompt(
        self,
        anomaly_result: Dict[str, Any],
        device_context: Dict[str, Any],
    ) -> str:
        return (
            "An anomaly was detected on a power meter that I cannot explain locally.\n\n"
            f"**Anomaly result:**\n```json\n{json.dumps(anomaly_result, indent=2, default=str)}\n```\n\n"
            f"**Device context:**\n```json\n{json.dumps(device_context, indent=2, default=str)}\n```\n\n"
            "Please explain the likely cause and suggest corrective action. "
            "Respond with JSON: {\"explanation\": \"...\", \"suggested_action\": \"...\", "
            "\"confidence\": 0.0-1.0}"
        )

    @staticmethod
    def _parse_identification_response(raw: str) -> Dict[str, Any]:
        import re

        text = raw

        # Strip markdown code block wrappers (```json ... ``` or ``` ... ```)
        md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if md_match:
            text = md_match.group(1)

        try:
            # Try to extract JSON from response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {
            "model": "unknown",
            "confidence": 0.0,
            "reasoning": raw[:500],
            "byte_order": "unknown",
        }

    @staticmethod
    def _parse_anomaly_response(raw: str) -> Dict[str, Any]:
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {
            "explanation": raw[:500],
            "suggested_action": "Manual investigation recommended.",
            "confidence": 0.0,
        }


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

_SYSTEM_MSG = (
    "You are an expert on industrial power meters (MFMs) and Modbus/OPC-UA protocols. "
    "You help identify unknown devices from their register values and resolve anomalies. "
    "Always respond with valid JSON as requested."
)

import re as _re
_IP_RE = _re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _looks_like_ip(s: str) -> bool:
    return bool(_IP_RE.search(s))
