"""Core HTTP client adapter with retry/timeout/error mapping."""

from __future__ import annotations

import json
import socket
import time
from typing import Any
from urllib import error, request

from contracts.v1.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    DiscussRequest,
    DiscussResponse,
    ReEvaluateFindingRequest,
    ReEvaluateFindingResponse,
)


class CoreClientError(Exception):
    """Base exception for Core client failures."""


class CoreClientHTTPError(CoreClientError):
    """Raised for non-success HTTP responses from Core."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Core API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class CoreClient:
    """HTTP adapter for the stateless Core API."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 30.0,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def health(self) -> dict[str, Any]:
        """Check Core liveness/readiness."""
        return self._request_json("GET", "/health")

    def analyze(self, req: AnalyzeRequest) -> AnalyzeResponse:
        """Call ``POST /v1/analyze`` and validate response contract."""
        payload = req.model_dump(by_alias=True)
        data = self._request_json("POST", "/v1/analyze", payload)
        return AnalyzeResponse.model_validate(data)

    def discuss(self, req: DiscussRequest) -> DiscussResponse:
        """Call ``POST /v1/discuss`` and validate response contract."""
        payload = req.model_dump(by_alias=True)
        data = self._request_json("POST", "/v1/discuss", payload)
        return DiscussResponse.model_validate(data)

    def re_evaluate(self, req: ReEvaluateFindingRequest) -> ReEvaluateFindingResponse:
        """Call ``POST /v1/re-evaluate-finding`` and validate response contract."""
        payload = req.model_dump(by_alias=True)
        data = self._request_json("POST", "/v1/re-evaluate-finding", payload)
        return ReEvaluateFindingResponse.model_validate(data)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a JSON request with retry and normalized error handling."""
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None

        for attempt in range(1, self.retry_attempts + 1):
            req = request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method=method,
            )
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = resp.read().decode("utf-8")
                    if not raw:
                        return {}
                    return json.loads(raw)
            except error.HTTPError as e:
                detail = self._read_http_error_detail(e)
                if e.code >= 500 and attempt < self.retry_attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise CoreClientHTTPError(e.code, detail) from e
            except (error.URLError, TimeoutError, socket.timeout) as e:
                if attempt < self.retry_attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise CoreClientError(f"Core API request failed after retries: {e}") from e
            except json.JSONDecodeError as e:
                raise CoreClientError(f"Core API returned invalid JSON: {e}") from e

        raise CoreClientError("Core API request failed")

    @staticmethod
    def _read_http_error_detail(exc: error.HTTPError) -> str:
        try:
            body = exc.read().decode("utf-8")
            if not body:
                return exc.reason or "HTTP error"
            try:
                payload = json.loads(body)
                if isinstance(payload, dict) and "detail" in payload:
                    return str(payload["detail"])
            except json.JSONDecodeError:
                pass
            return body
        except Exception:
            return str(exc.reason or "HTTP error")

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff_seconds <= 0:
            return
        time.sleep(self.retry_backoff_seconds * attempt)
