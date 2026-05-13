from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

_DEFAULT_GENIE = Path.home() / "genie4cv" / "local.settings.json"
_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_ROOT / ".env", override=False)
    except ImportError:
        pass


def settings_path() -> Path:
    return Path(os.getenv("GENIE4CV_SETTINGS", str(_DEFAULT_GENIE)))


def load_genie_values() -> Dict[str, Any]:
    p = settings_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data.get("Values", {}) if isinstance(data, dict) else {}


_load_dotenv()
SETTINGS: Dict[str, Any] = load_genie_values()


def get_setting(*keys: str, default: str = "") -> str:
    """Env wins, then Genie4CV Values JSON."""
    for key in keys:
        v = os.getenv(key) or SETTINGS.get(key)
        if v:
            return str(v)
    return default
