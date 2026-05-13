from __future__ import annotations

import requests

SERPAPI_URL = "https://serpapi.com/search"


def serpapi_request(params: dict, timeout: int = 45) -> dict:
    response = requests.get(SERPAPI_URL, params=params, timeout=timeout)
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
