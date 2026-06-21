from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


BASE_URL = "https://data.solanatracker.io"


class ApiError(RuntimeError):
    def __init__(self, endpoint: str, status_code: int | None, message: str, latency_ms: int):
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code
        self.latency_ms = latency_ms


@dataclass
class ApiResult:
    data: Any
    endpoint: str
    status_code: int
    latency_ms: int


class SolanaTrackerClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("SOLANA_TRACKER_API_KEY is missing")
        self.api_key = api_key

    def _get(self, path: str, params: dict[str, Any] | None = None) -> ApiResult:
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        endpoint = f"{path}?{query}" if query else path
        url = f"{BASE_URL}{endpoint}"
        request = urllib.request.Request(url, headers={"x-api-key": self.api_key})
        started = time.perf_counter()

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
                latency_ms = int((time.perf_counter() - started) * 1000)
                data = json.loads(body) if body else None
                return ApiResult(data=data, endpoint=endpoint, status_code=response.status, latency_ms=latency_ms)
        except urllib.error.HTTPError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            body = exc.read().decode("utf-8", errors="replace")
            raise ApiError(endpoint, exc.code, body[:500], latency_ms) from exc
        except urllib.error.URLError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            raise ApiError(endpoint, None, str(exc.reason), latency_ms) from exc

    def subscription(self) -> ApiResult:
        return self._get("/subscription")

    def latest_tokens(self, page: int = 1) -> ApiResult:
        return self._get("/tokens/latest", {"page": page})

    def token_info(self, token_address: str) -> ApiResult:
        return self._get(f"/tokens/{urllib.parse.quote(token_address)}")

    def token_trades(self, token_address: str, cursor: str | None = None) -> ApiResult:
        return self._get(
            f"/trades/{urllib.parse.quote(token_address)}",
            {"cursor": cursor, "hideArb": "true", "sortDirection": "DESC"},
        )
