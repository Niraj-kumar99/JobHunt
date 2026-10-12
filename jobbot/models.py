"""Core data structure shared by every job source."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional


@dataclass
class Job:
    company: str
    title: str
    url: str
    source: str
    job_id: str = ""
    location: str = ""
    country_code: str = ""          # ISO-2 when the source provides it
    remote: Optional[bool] = None
    posted: Optional[date] = None
    posted_text: str = ""           # raw text, e.g. "Posted 3 Days Ago"
    description: str = ""           # plain text
    language: str = ""              # ISO-639-1 when the source provides it
    experience_level: str = ""      # normalised: intern / entry / mid / senior / ""
    years_hint: str = ""            # structured years-of-experience field, if any
    months_required: Optional[int] = None
    detail: Optional[Callable[["Job"], None]] = field(default=None, repr=False, compare=False)
    detail_loaded: bool = False
    # filled in by the pipeline
    first_seen: Optional[date] = None
    date_is_first_seen: bool = False
    notes: list = field(default_factory=list)

    def key(self) -> str:
        ident = self.job_id or self.url or self.title
        raw = f"{self.company}|{self.source}|{ident}".lower()
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def load_detail(self) -> None:
        """Fetch the full posting (description, exact location) when the list view lacked it."""
        if self.detail and not self.detail_loaded:
            try:
                self.detail(self)
            finally:
                self.detail_loaded = True
