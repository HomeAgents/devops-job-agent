from __future__ import annotations

import time

import requests

SERPAPI_URL = "https://serpapi.com/search"

_MAX_RETRIES = 2
_BACKOFF_BASE = 2.0


def serpapi_request(params: dict, timeout: int = 45) -> dict:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.get(SERPAPI_URL, params=params, timeout=timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"SerpAPI network error: {exc}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            last_exc = RuntimeError(
                f"SerpAPI HTTP {response.status_code} (attempt {attempt + 1})"
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE ** (attempt + 1))
                continue

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"SerpAPI returned non-JSON (HTTP {response.status_code})") from exc

        if response.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            raise RuntimeError(f"SerpAPI HTTP {response.status_code}: {err or 'request failed'}")

        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"SerpAPI error: {data['error']}")

        return data

    raise last_exc  # type: ignore[misc]
