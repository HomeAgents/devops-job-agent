from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Job:
    source: str
    company: str
    title: str
    location: str
    link: str
    posted: str = "recent"
    score: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> Dict[str, Any]:
        return {
            "Company": self.company,
            "Job Title": self.title,
            "Location": self.location,
            "Posted Date": self.posted,
            "Link": self.link,
            "Score": self.score,
            "Source": self.source,
        }
