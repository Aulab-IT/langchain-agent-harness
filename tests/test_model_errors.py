from __future__ import annotations

import pytest

from agent_harness.model_errors import invoke_with_model_retry, model_error_details


class APIError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.body = {
            "message": message,
            "type": "server_error",
            "code": "stream_failed",
        }
        self.request_id = "req_test123"


def test_model_error_details_keep_diagnostics_and_redact_secrets() -> None:
    details = model_error_details(APIError("retry request with sk-secret123456789"))

    assert details == {
        "exception_type": "APIError",
        "message": "retry request with [REDACTED]",
        "transient": True,
        "request_id": "req_test123",
        "provider_error_type": "server_error",
        "provider_error_code": "stream_failed",
    }


@pytest.mark.asyncio
async def test_transient_model_error_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    events: list[dict[str, object]] = []
    retry_details: list[dict[str, object]] = []

    async def no_sleep(_: float) -> None:
        return None

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise APIError("You can retry your request")
        return "ok"

    monkeypatch.setattr("agent_harness.model_errors.asyncio.sleep", no_sleep)
    result = await invoke_with_model_retry(
        operation,
        event_callback=events.append,
        call_kind="subagent:builder",
        model="test-model",
        on_retry=lambda _exc, details: retry_details.append(details),
    )

    assert result == "ok"
    assert attempts == 2
    assert events[0]["type"] == "model.retrying"
    assert events[0]["request_id"] == "req_test123"
    assert retry_details[0]["provider_error_code"] == "stream_failed"


@pytest.mark.asyncio
async def test_deterministic_model_error_does_not_retry() -> None:
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("invalid schema")

    with pytest.raises(ValueError, match="invalid schema"):
        await invoke_with_model_retry(
            operation,
            call_kind="root:low",
            model="test-model",
        )

    assert attempts == 1
