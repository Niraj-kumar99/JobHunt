"""Readers for the job platforms that large European employers use.

Each reader is a generator: reader(company_name, ats_id, http, ctx) -> Iterator[Job].
Platforms with a public JSON/XML feed are read directly; anything else falls back to the
generic reader, which looks for structured JobPosting data and job links on the careers page.
"""
from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from typing import Iterator
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .models import Job
from .textutil import html_to_text, parse_date

LEVEL_MAP = {
    # SmartRecruiters / LinkedIn-style
    "internship": "intern", "intern": "intern", "student": "intern", "student_college": "intern",
    "entry_level": "entry", "entry level": "entry", "entry-level": "entry", "associate": "entry",
    "junior": "entry", "graduate": "entry", "lt-1": "entry",
    "mid_level": "mid", "mid-level": "mid", "mid_senior_level": "senior", "mid-senior level": "senior",
    "experienced": "mid", "senior": "senior", "director": "senior", "executive": "senior",
    "manager": "senior",
}


def norm_level(value) -> str:
    if not value:
        return ""
    return LEVEL_MAP.get(str(value).strip().lower(), "")


# --------------------------------------------------------------------------- Greenhouse
def greenhouse(company: str, token: str, http, ctx) -> Iterator[Job]:
    data = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                         params={"content": "true"})
    for j in data.get("jobs", []):
        yield Job(
            company=company, source="greenhouse", job_id=str(j.get("id", "")),
            title=j.get("title", ""), url=j.get("absolute_url", ""),
            location=(j.get("location") or {}).get("name", ""),
            posted=parse_date(j.get("first_published") or j.get("updated_at")),
            description=html_to_text(html.unescape(j.get("content") or "")),
            detail_loaded=True,
        )


# --------------------------------------------------------------------------- Lever
def lever(company: str, ident: str, http, ctx) -> Iterator[Job]:
    base = "https://api.lever.co"
    if ident.startswith("eu/"):
        base, ident = "https://api.eu.lever.co", ident[3:]
    data = http.get_json(f"{base}/v0/postings/{ident}", params={"mode": "json"})
    for p in data or []:
        cats = p.get("categories") or {}
        locs = cats.get("allLocations") or [cats.get("location") or ""]
        parts = [p.get("descriptionPlain") or ""]
        for lst in p.get("lists") or []:
            parts.append(lst.get("text", ""))
            parts.append(html_to_text(lst.get("content", "")))
        parts.append(p.get("additionalPlain") or "")
        yield Job(
            company=company, source="lever", job_id=p.get("id", ""),
            title=p.get("text", ""), url=p.get("hostedUrl", ""),
            location="; ".join(x for x in locs if x),
            country_code=(p.get("country") or "").upper(),
            remote=(p.get("workplaceType") == "remote") or None,
            posted=parse_date(p.get("createdAt")),
            description="\n".join(x for x in parts if x),
            detail_loaded=True,
        )


# --------------------------------------------------------------------------- Ashby
def ashby(company: str, org: str, http, ctx) -> Iterator[Job]:
    data = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{org}",
                         params={"includeCompensation": "false"})
    for j in data.get("jobs", []):
        locs = [j.get("location") or ""]
        locs += [s.get("location", "") for s in j.get("secondaryLocations") or []]
        country = (((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or "")
        if country and country not in locs:
            locs.append(country)
        yield Job(
            company=company, source="ashby", job_id=j.get("id", ""),
            title=j.get("title", ""), url=j.get("jobUrl", ""),
            location="; ".join(x for x in locs if x),
            remote=bool(j.get("isRemote")) or None,
            posted=parse_date(j.get("publishedAt")),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            detail_loaded=True,
        )


# --------------------------------------------------------------------------- SmartRecruiters
def smartrecruiters(company: str, cid: str, http, ctx) -> Iterator[Job]:
    seen = set()
    for term in ctx.search_terms:
        offset = 0
        while offset < 300:
            data = http.get_json(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings",
                                 params={"q": term, "limit": 100, "offset": offset})
            items = data.get("content", [])
            for p in items:
                pid = p.get("id")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                loc = p.get("location") or {}
                yield Job(
                    company=company, source="smartrecruiters", job_id=pid,
                    title=p.get("name", ""),
                    url=f"https://jobs.smartrecruiters.com/{cid}/{pid}",
                    location=loc.get("fullLocation") or ", ".join(
                        x for x in (loc.get("city"), loc.get("country")) if x),
                    country_code=(loc.get("country") or "").upper(),
                    remote=loc.get("remote"),
                    posted=parse_date(p.get("releasedDate")),
                    language=((p.get("language") or {}).get("code") or "")[:2],
                    experience_level=norm_level((p.get("experienceLevel") or {}).get("id")),
                    detail=_sr_detail(cid, pid, http),
                )
            if len(items) < 100:
                break
            offset += 100


def _sr_detail(cid, pid, http):
    def load(job: Job):
        d = http.get_json(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings/{pid}")
        sections = ((d.get("jobAd") or {}).get("sections") or {})
        job.description = "\n".join(html_to_text((sections.get(k) or {}).get("text"))
                                    for k in ("jobDescription", "qualifications",
                                              "additionalInformation", "companyDescription"))
        job.url = d.get("postingUrl") or job.url
    return load


# --------------------------------------------------------------------------- Workable
def workable(company: str, sub: str, http, ctx) -> Iterator[Job]:
    data = http.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{sub}",
                         params={"details": "true"})
    for j in data.get("jobs", []):
        locs = j.get("locations") or [{"city": j.get("city"), "country": j.get("country"),
                                       "countryCode": ""}]
        loc_text = "; ".join(", ".join(x for x in (l.get("city"), l.get("country")) if x) for l in locs)
        code = (locs[0].get("countryCode") or "").upper() if len(locs) == 1 else ""
        yield Job(
            company=company, source="workable", job_id=j.get("shortcode", ""),
            title=j.get("title", ""), url=j.get("url") or j.get("shortlink", ""),
            location=loc_text, country_code=code,
            remote=bool(j.get("telecommuting")) or None,
            posted=parse_date(j.get("published_on") or j.get("created_at")),
            experience_level=norm_level(j.get("experience")),
            description=html_to_text(j.get("description")),
            detail_loaded=bool(j.get("description")),
        )


# --------------------------------------------------------------------------- Recruitee
def recruitee(company: str, sub: str, http, ctx) -> Iterator[Job]:
    data = http.get_json(f"https://{sub}.recruitee.com/api/offers/")
    for o in data.get("offers", []):
        yield Job(
            company=company, source="recruitee", job_id=str(o.get("id", "")),
            title=o.get("title", ""), url=o.get("careers_url", ""),
            location=o.get("location") or ", ".join(x for x in (o.get("city"), o.get("country")) if x),
            country_code=(o.get("country_code") or "").upper(),
            remote=o.get("remote"),
            posted=parse_date(o.get("published_at") or o.get("created_at")),
            experience_level=norm_level(o.get("experience_code")),
            description=html_to_text((o.get("description") or "") + "\n" + (o.get("requirements") or "")),
            detail_loaded=True,
        )


# --------------------------------------------------------------------------- Personio
def personio(company: str, sub: str, http, ctx) -> Iterator[Job]:
    host = sub if "." in sub else f"{sub}.jobs.personio.de"
    root = ET.fromstring(http.get(f"https://{host}/xml", params={"language": "en"}).content)
    for pos in root.iter("position"):
        def t(tag):
            el = pos.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        offices = [t("office")] + [(o.text or "").strip() for o in pos.findall("additionalOffices/office")]
        desc = "\n".join(
            html_to_text((jd.findtext("name") or "") + "\n" + (jd.findtext("value") or ""))
            for jd in pos.findall("jobDescriptions/jobDescription"))
        pid = t("id")
        yield Job(
            company=company, source="personio", job_id=pid, title=t("name"),
            url=f"https://{host}/job/{pid}?language=en",
            location="; ".join(o for o in offices if o),
            posted=parse_date(t("createdAt")),
            experience_level=norm_level(t("seniority")) or norm_level(t("yearsOfExperience")),
            years_hint=t("yearsOfExperience"),
            description=desc, detail_loaded=True,
        )


# --------------------------------------------------------------------------- Workday
def workday(company: str, ident: str, http, ctx) -> Iterator[Job]:
    host, tenant, site = ident.split("|")
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    seen = set()
    for term in ctx.search_terms:
        for page in range(5):
            data = http.post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 20,
                                                  "offset": page * 20, "searchText": term})
            items = data.get("jobPostings") or []
            for p in items:
                path = p.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                loc = p.get("locationsText") or ""
                yield Job(
                    company=company, source="workday", job_id=path, title=p.get("title", ""),
                    url=f"https://{host}/en-US/{site}{path}",
                    location="" if re.match(r"^\d+ Locations?$", loc) else loc,
                    posted=parse_date(p.get("postedOn")), posted_text=p.get("postedOn", ""),
                    detail=_wd_detail(api, path, http),
                    )
            if len(items) < 20:
                break


def _wd_detail(api, path, http):
    def load(job: Job):
        info = (http.get_json(f"{api}{path}").get("jobPostingInfo") or {})
        job.description = html_to_text(info.get("jobDescription"))
        locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
        country = (info.get("country") or {}).get("descriptor", "")
        if country:
            locs.append(country)
        job.location = "; ".join(x for x in locs if x) or job.location
        job.posted = parse_date(info.get("startDate")) or job.posted
        job.url = info.get("externalUrl") or job.url
    return load


# --------------------------------------------------------------------------- SuccessFactors (RSS)
def successfactors(company: str, host: str, http, ctx) -> Iterator[Job]:
    seen = set()
    for term in ctx.search_terms:
        url = f"https://{host}/services/rss/job/?locale=en_US&keywords=({quote(term)})"
        root = ET.fromstring(http.get(url).content)
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            raw_title = (item.findtext("title") or "").strip()
            m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", raw_title)
            title, loc = (m.group(1), m.group(2)) if m else (raw_title, "")
            desc = html_to_text(item.findtext("description"))
            yield Job(
                company=company, source="successfactors", job_id=link, title=title, url=link,
                location=loc, posted=parse_date(item.findtext("pubDate")), description=desc,
                detail=None if len(desc) > 300 else _page_detail(link, http),
                detail_loaded=len(desc) > 300,
            )


# --------------------------------------------------------------------------- Generic fallback
def _iter_jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "@graph" in node:
                    stack.extend(node["@graph"] if isinstance(node["@graph"], list) else [node["@graph"]])
                types = node.get("@type")
                types = types if isinstance(types, list) else [types]
                if "JobPosting" in types:
                    yield node
                for key in ("itemListElement", "item"):
                    if key in node:
                        stack.append(node[key])


def _jsonld_location(node) -> tuple[str, str, bool]:
    locs, code = [], ""
    jl = node.get("jobLocation") or []
    for place in (jl if isinstance(jl, list) else [jl]):
        addr = (place or {}).get("address") or {}
        if isinstance(addr, str):
            locs.append(addr)
            continue
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name") or country.get("identifier")
        country = country or ""
        if len(str(country)) == 2:
            code = str(country).upper()
        locs.append(", ".join(str(x) for x in (addr.get("addressLocality"), country) if x))
    for req in (node.get("applicantLocationRequirements") or []) if isinstance(
            node.get("applicantLocationRequirements"), list) else [node.get("applicantLocationRequirements") or {}]:
        if isinstance(req, dict) and req.get("name"):
            locs.append(req["name"])
    remote = str(node.get("jobLocationType", "")).upper() == "TELECOMMUTE"
    return "; ".join(x for x in locs if x), code, remote


def _job_from_jsonld(company: str, node: dict, page_url: str) -> Job:
    loc, code, remote = _jsonld_location(node)
    exp = node.get("experienceRequirements")
    months = None
    if isinstance(exp, dict) and exp.get("monthsOfExperience") is not None:
        try:
            months = int(float(exp["monthsOfExperience"]))
        except (TypeError, ValueError):
            months = None
    url = node.get("url") or page_url
    return Job(
        company=company, source="generic", job_id=str(node.get("identifier", {}).get("value", "")
                                                       if isinstance(node.get("identifier"), dict) else url),
        title=html.unescape(str(node.get("title", ""))), url=url,
        location=loc, country_code=code, remote=remote or None,
        posted=parse_date(node.get("datePosted")),
        language=str(node.get("inLanguage") or "")[:2].lower(),
        description=html_to_text(node.get("description")),
        experience_level=norm_level(node.get("experienceLevel")),
        months_required=months, detail_loaded=True,
    )


def _page_detail(url, http):
    def load(job: Job):
        r = http.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        for node in _iter_jsonld(soup):
            rich = _job_from_jsonld(job.company, node, url)
            job.description = rich.description or job.description
            job.location = rich.location or job.location
            job.country_code = rich.country_code or job.country_code
            job.posted = rich.posted or job.posted
            job.language = rich.language or job.language
            job.months_required = rich.months_required
            return
        main = soup.find("main") or soup.body or soup
        job.description = html_to_text(str(main))[:20000]
        lang = (soup.html.get("lang") if soup.html else "") or ""
        job.language = job.language or lang[:2].lower()
    return load


def generic(company: str, url: str, http, ctx) -> Iterator[Job]:
    r = http.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    found = False
    for node in _iter_jsonld(soup):
        found = True
        yield _job_from_jsonld(company, node, r.url)
    if found:
        return
    # No structured data: collect links whose text looks like one of the target job titles.
    count = 0
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ").split())
        if not text or len(text) > 140 or not ctx.title_matches(text):
            continue
        link = urljoin(r.url, a["href"])
        if urlparse(link).scheme not in ("http", "https"):
            continue
        count += 1
        yield Job(company=company, source="generic", job_id=link, title=text, url=link,
                  detail=_page_detail(link, http))
        if count >= 15:
            break


READERS = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
    "workable": workable, "recruitee": recruitee, "personio": personio, "workday": workday,
    "successfactors": successfactors, "generic": generic,
}
