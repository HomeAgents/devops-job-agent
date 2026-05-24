"""Outbound email language: auto-detect from user message (en | he | ru)."""
from __future__ import annotations

import os
import re
from typing import Any, Optional

_HE = re.compile(r"[\u0590-\u05FF]")
_RU = re.compile(r"[\u0400-\u04FF]")
_EN = re.compile(r"[A-Za-z]")


def _normalize_lang(raw: str) -> str:
    s = (raw or "en").strip().lower()
    if s in ("he", "hebrew", "iw"):
        return "he"
    if s in ("ru", "russian"):
        return "ru"
    return "en"


def default_language() -> str:
    return _normalize_lang(os.getenv("ORCHESTRATOR_LANGUAGE") or "en")


def detect_language_from_text(text: str) -> str:
    """Infer reply language from email body (script counts)."""
    if not (text or "").strip():
        return default_language()
    he = len(_HE.findall(text))
    ru = len(_RU.findall(text))
    en = len(_EN.findall(text))
    if he > 0 and he >= ru and he >= en:
        return "he"
    if ru > 0 and ru >= he and ru >= en:
        return "ru"
    return "en"


def lang_from_meta(meta: Optional[dict[str, Any]]) -> str:
    if meta and meta.get("reply_language"):
        return _normalize_lang(str(meta["reply_language"]))
    return default_language()


def tr(en: str, he: str, ru: str, lang: Optional[str] = None) -> str:
    code = _normalize_lang(lang) if lang else default_language()
    if code == "he":
        return he
    if code == "ru":
        return ru
    return en
