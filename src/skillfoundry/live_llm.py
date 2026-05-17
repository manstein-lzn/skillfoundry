"""Opt-in live provider clients for SkillFoundry-owned LLM calls."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping
from urllib import error, request

from contextforge.schema import ModelResponse, UsageDraft


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_FRONTDESK_MODEL = "gpt-5.5"


class OpenAIChatCompletionsClient:
    """Small stdlib OpenAI-compatible chat completions client.

    The client is intentionally not wired into default tests. It is used only
    when the operator starts the API with ``OPENAI_API_KEY`` configured or when
    a caller explicitly injects it.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        timeout_seconds: int = 60,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must be non-empty")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "OpenAIChatCompletionsClient":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key.strip():
            raise RuntimeError("OPENAI_API_KEY is not set")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            timeout_seconds=int(os.environ.get("SKILLFOUNDRY_FRONTDESK_TIMEOUT_SECONDS", "60")),
        )

    def invoke(self, messages: list[Any], model: str, params: Mapping[str, Any], tools: list[dict[str, Any]] | None = None):
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": str(params.get("model") or model),
            "messages": [_message_to_openai(message) for message in messages],
            "response_format": {"type": "json_object"},
        }
        for key, value in dict(params).items():
            if value is None:
                continue
            if key in {"provider", "model"}:
                continue
            payload[key] = value
        if tools:
            payload["tools"] = tools

        raw = _post_json(
            f"{self.base_url}/chat/completions",
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )
        choice = (raw.get("choices") or [{}])[0]
        message = choice.get("message") if isinstance(choice, dict) else {}
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("OpenAI response did not include message.content")
        usage_payload = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        prompt_details = usage_payload.get("prompt_tokens_details") if isinstance(usage_payload, dict) else {}
        usage = UsageDraft(
            input_tokens=_optional_int(usage_payload.get("prompt_tokens")),
            cached_input_tokens=_optional_int(prompt_details.get("cached_tokens")) if isinstance(prompt_details, dict) else None,
            cache_telemetry_status="reported"
            if isinstance(prompt_details, dict) and prompt_details.get("cached_tokens") is not None
            else "unavailable",
            output_tokens=_optional_int(usage_payload.get("completion_tokens")),
            cost_usd=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider_payload=usage_payload if isinstance(usage_payload, dict) else {},
        )
        return (
            ModelResponse(
                text=text,
                raw_response_artifact_ref=None,
                finish_reason=str(choice.get("finish_reason")) if isinstance(choice, dict) and choice.get("finish_reason") else None,
                metadata={"provider": "openai", "response_id": raw.get("id")},
            ),
            None,
            usage,
        )


def _message_to_openai(message: Any) -> dict[str, str]:
    if hasattr(message, "to_dict"):
        message = message.to_dict()
    if not isinstance(message, Mapping):
        raise TypeError("message must be a mapping or schema message")
    role = str(message.get("role") or "user")
    if role == "developer":
        role = "system"
    if role not in {"system", "user", "assistant", "tool"}:
        role = "user"
    return {"role": role, "content": str(message.get("content") or "")}


def _post_json(url: str, payload: Mapping[str, Any], *, api_key: str, timeout_seconds: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("OpenAI response was not a JSON object")
    return decoded


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "DEFAULT_FRONTDESK_MODEL",
    "DEFAULT_OPENAI_BASE_URL",
    "OpenAIChatCompletionsClient",
]
