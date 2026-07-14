"""Classificazione provider-neutral e retry sicuro delle chiamate modello."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

T = TypeVar("T")
EventSink = Callable[[dict[str, Any]], None]
RetryHook = Callable[[Exception, dict[str, Any]], None]

_REQUEST_ID = re.compile(r"\breq_[A-Za-z0-9_-]+\b")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{8,}"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
)
_TRANSIENT_NAMES = {
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "InternalServerError",
    "OverloadedError",
    "RateLimitError",
    "ServiceUnavailableError",
}


def _safe_message(value: Any, limit: int = 500) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: (
                f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]"
            ),
            text,
        )
    return text[:limit]


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if not isinstance(value, int):
        value = getattr(getattr(exc, "response", None), "status_code", None)
    return value if isinstance(value, int) else None


def _error_body(exc: Exception) -> Mapping[str, Any]:
    body = getattr(exc, "body", None)
    if not isinstance(body, Mapping):
        return {}
    nested = body.get("error")
    return nested if isinstance(nested, Mapping) else body


def is_transient_model_error(exc: Exception) -> bool:
    status_code = _status_code(exc)
    if status_code is not None:
        return status_code in {408, 409, 429} or status_code >= 500
    name = type(exc).__name__
    text = str(exc).lower()
    return name in _TRANSIENT_NAMES or any(
        marker in text
        for marker in (
            "try again",
            "retry your request",
            "temporarily unavailable",
            "overloaded",
            "connection reset",
            "timed out",
        )
    )


def model_error_details(exc: Exception) -> dict[str, Any]:
    """Dettagli diagnostici consentiti nel trace; mai headers, payload o credenziali."""
    body = _error_body(exc)
    message = _safe_message(body.get("message") or str(exc))
    request_id = getattr(exc, "request_id", None)
    if not isinstance(request_id, str) or not request_id:
        headers = getattr(getattr(exc, "response", None), "headers", None)
        header_id = headers.get("x-request-id") if isinstance(headers, Mapping) else None
        request_id = header_id if isinstance(header_id, str) else None
    if not request_id:
        match = _REQUEST_ID.search(str(exc))
        request_id = match.group(0) if match else None
    details: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "message": message,
        "transient": is_transient_model_error(exc),
    }
    status_code = _status_code(exc)
    if status_code is not None:
        details["status_code"] = status_code
    if request_id:
        details["request_id"] = request_id[:200]
    for source, target in (
        ("type", "provider_error_type"),
        ("code", "provider_error_code"),
        ("param", "provider_error_param"),
    ):
        value = body.get(source)
        if isinstance(value, (str, int, float, bool)):
            details[target] = _safe_message(value, 200)
    return details


async def invoke_with_model_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    event_callback: EventSink | None = None,
    call_kind: str,
    model: str,
    on_retry: RetryHook | None = None,
    max_attempts: int = 2,
) -> T:
    """Riprova una volta gli errori transitori; errori deterministici falliscono subito."""
    attempts = max(1, max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            details = model_error_details(exc)
            retry = bool(details["transient"]) and attempt < attempts
            event_type = (
                "model.retrying"
                if retry
                else "model.retry_exhausted"
                if details["transient"]
                else "model.request_failed"
            )
            if event_callback is not None:
                event_callback(
                    {
                        "type": event_type,
                        "call_kind": call_kind,
                        "model": model,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        **details,
                    }
                )
            if not retry:
                raise
            if on_retry is not None:
                on_retry(exc, details)
            await asyncio.sleep(0.5 * attempt)
    raise RuntimeError("unreachable")


__all__ = [
    "invoke_with_model_retry",
    "is_transient_model_error",
    "model_error_details",
]
