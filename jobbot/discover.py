"""Work out which job platform a careers page runs on, so we can read its feed directly."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Order matters: the first platform found wins.
PATTERNS = [
    ("workday", re.compile(
        r"https?://(?P<tenant>[\w-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[\w-]+)")),
    ("greenhouse", re.compile(
        r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?(?P<id>[\w-]+)")),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/(?P<id>[\w-]+)")),
    ("lever", re.compile(r"jobs\.(?P<eu>eu\.)?lever\.co/(?P<id>[\w.-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/(?P<id>[\w.%-]+)")),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/(?P<id>[\w-]+)")),
    ("smartrecruiters", re.compile(r"api\.smartrecruiters\.com/v1/companies/(?P<id>[\w-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/(?P<id>[\w-]+)")),
    ("recruitee", re.compile(r"(?P<id>[\w-]+)\.recruitee\.com")),
    ("personio", re.compile(r"(?P<id>[\w-]+\.jobs\.personio\.(?:de|com))")),
]
_BAD_IDS = {"embed", "js", "v1", "api", "static", "assets", "jobs", "careers", "www", "widget", "wday",
            "en", "de", "fr", "search", "j", "o"}
_JOB_LINK_TEXT = re.compile(
    r"(search|view|see|browse|explore|find|all|open|current)\s+(all\s+)?(jobs|positions|roles|vacancies|openings|opportunities)"
    r"|job\s+search|stellenangebote|offres d'emploi", re.I)


def detect_in_text(text: str) -> tuple[str, str] | None:
    for ats, rx in PATTERNS:
        for m in rx.finditer(text):
            if ats == "workday":
                site = m.group("site")
                if site.lower() in _BAD_IDS:
                    continue
                host = f"{m.group('tenant')}.{m.group('wd')}.myworkdayjobs.com"
                return ats, f"{host}|{m.group('tenant')}|{site}"
            ident = m.group("id")
            if ident.lower() in _BAD_IDS:
                continue
            if ats == "lever" and m.group("eu"):
                ident = f"eu/{ident}"
            return ats, ident
    return None


def _successfactors_host(final_url: str, html: str) -> str | None:
    if re.search(r"rmkcdn\.successfactors\.com|/services/rss/job/|jobs2web", html, re.I):
        return urlparse(final_url).netloc
    return None


def discover(careers_url: str, http) -> tuple[str, str, str]:
    """Returns (platform, platform_id, note). Falls back to ("generic", url, ...)."""
    r = http.get(careers_url)
    text = r.url + "\n" + r.text
    hit = detect_in_text(text)
    if hit:
        return hit[0], hit[1], "found on careers page"
    sf = _successfactors_host(r.url, r.text)
    if sf:
        return "successfactors", sf, "SuccessFactors career site"
    # One hop: follow a "search jobs" style link and look again.
    soup = BeautifulSoup(r.text, "html.parser")
    candidates = []
    for a in soup.find_all(["a", "iframe"]):
        href = a.get("href") or a.get("src")
        if not href:
            continue
        label = " ".join(a.get_text(" ").split()) if a.name == "a" else "iframe"
        if a.name == "iframe" or _JOB_LINK_TEXT.search(label) or re.search(r"/(jobs|search|vacancies|job-search|stellen)\b", href, re.I):
            candidates.append(urljoin(r.url, href))
    for link in list(dict.fromkeys(candidates))[:3]:
        if urlparse(link).scheme not in ("http", "https"):
            continue
        hit = detect_in_text(link)
        if hit:
            return hit[0], hit[1], "found via job search link"
        try:
            r2 = http.get(link)
        except Exception:
            continue
        hit = detect_in_text(r2.url + "\n" + r2.text)
        if hit:
            return hit[0], hit[1], "found via job search page"
        sf = _successfactors_host(r2.url, r2.text)
        if sf:
            return "successfactors", sf, "SuccessFactors career site"
    return "generic", r.url, "no job platform detected; reading page directly"
