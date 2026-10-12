"""Small helpers for turning HTML into text and parsing the many date formats job feeds use."""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

_BLOCK_TAGS = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|section|article)[^>]*>", re.I)
_DROP = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = _DROP.sub(" ", value)
    text = _BLOCK_TAGS.sub("\n", text)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def today() -> date:
    return datetime.now(timezone.utc).date()


_REL = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.I)


def parse_date(value, ref: Optional[date] = None) -> Optional[date]:
    """Accepts ISO strings, epoch seconds/ms, RFC-822 dates and Workday-style relative text."""
    ref = ref or today()
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:  # milliseconds
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if s.isdigit():
        return parse_date(int(s), ref)
    m = _REL.search(s)
    if m:
        word = m.group(1).lower()
        if word == "today":
            return ref
        if word == "yesterday":
            return ref - timedelta(days=1)
        return ref - timedelta(days=int(m.group(2)))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$", s)  # 09.10.2026 (European order)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    try:
        return parsedate_to_datetime(s).date()
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
