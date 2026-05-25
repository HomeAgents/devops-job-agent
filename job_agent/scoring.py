from __future__ import annotations

from typing import Any, Dict, List


def score_title(title: str, cfg: Dict[str, Any]) -> int:
    sc = cfg.get("scoring") or {}
    keywords: List[str] = sc.get("keywords") or ["DevOps", "Platform", "SRE"]
    seniority: List[str] = sc.get("seniority") or ["Manager", "Director", "Head", "Lead"]
    bonus = int(sc.get("director_head_bonus", 2))

    t = (title or "").lower()
    score = 0
    if any(s.lower() in t for s in seniority):
        score += 5
    if any(k.lower() in t for k in keywords):
        score += 3
    if "director" in t or "head" in t or "vp " in t or "vice president" in t:
        score += bonus
    if "devops" in t and ("manager" in t or "director" in t or "head" in t):
        score += 4
    return score


def title_matches_role_focus(title: str, cfg: Dict[str, Any]) -> bool:
    """Return True if the title has at least one scoring keyword hit.

    Used by ATS sources (Greenhouse, Lever) to drop completely irrelevant
    titles before they enter the pipeline.  Titles that match zero keywords
    from the scoring config are noise (e.g. "Customer Success Manager" when
    the user searches for DevOps roles).
    """
    sc = cfg.get("scoring") or {}
    keywords: List[str] = sc.get("keywords") or ["DevOps", "Platform", "SRE"]
    role_focus: List[str] = cfg.get("role_focus") or []

    t = (title or "").lower()
    if any(k.lower() in t for k in keywords):
        return True
    if any(r.lower() in t for r in role_focus):
        return True
    return False
