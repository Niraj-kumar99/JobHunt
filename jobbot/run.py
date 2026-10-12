"""The pipeline: for each company, read its jobs, keep new ones that pass every filter."""
from __future__ import annotations

import csv
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import filters
from .discover import discover
from .http import Http
from .models import Job
from .sources import READERS
from .storage import State
from .textutil import today as utc_today

ROOT = Path(__file__).resolve().parent.parent
MAX_JOBS_PER_COMPANY = 3000   # safety cap on any single feed


@dataclass
class Ctx:
    cfg: dict
    search_terms: list
    titles: list

    def title_matches(self, title: str) -> bool:
        return filters.title_matches(title, self.titles)


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("max_age_days", 5)
    cfg.setdefault("max_experience_years", 1)
    cfg.setdefault("allow_unstated_experience", False)
    cfg.setdefault("include_internships", False)
    cfg.setdefault("allow_unknown_language", True)
    cfg.setdefault("allow_unknown_location", True)
    cfg.setdefault("title_patterns", filters.DEFAULT_TITLE_PATTERNS)
    cfg.setdefault("search_terms", ["project manager", "product manager", "business analyst"])
    cfg.setdefault("workers", 8)
    cfg.setdefault("rediscover_after_days", 14)
    cfg.setdefault("seed_undated_on_first_run", True)
    cfg.setdefault("history_days", 30)
    return cfg


def load_companies(path: Path | None = None) -> list[dict]:
    with open(path or ROOT / "companies.csv", encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("name") or "").strip()]
    for r in rows:
        for k in ("ats", "ats_id", "careers_url"):
            r[k] = (r.get(k) or "").strip()
    return rows


# ----------------------------------------------------------------------------- filtering
def evaluate(job: Job, cfg: dict, ref: date, first_run: bool) -> tuple[bool, str]:
    """Returns (passes, reason). Loads the full posting only when the list view isn't enough."""
    max_age = cfg["max_age_days"]

    def load():
        if not job.detail_loaded:
            try:
                job.load_detail()
            except Exception as e:  # keep going with what the list view gave us
                job.notes.append(f"full posting unavailable ({type(e).__name__})")

    age = filters.age_days(job, ref)
    if age is not None and age > max_age:
        return False, "older than limit"

    where = filters.europe_status(job)
    if where is False:
        return False, "outside Europe"
    if where is None:
        load()
        where = filters.europe_status(job)
        if where is False:
            return False, "outside Europe"
        if where is None:
            if not cfg["allow_unknown_location"]:
                return False, "location unknown"
            job.notes.append("location not stated")

    load()
    age = filters.age_days(job, ref)
    if age is not None and age > max_age:
        return False, "older than limit"
    if age is None:
        if first_run and cfg["seed_undated_on_first_run"]:
            return False, "undated (first run)"
        job.posted = ref
        job.date_is_first_seen = True

    eng = filters.english_status(job)
    if eng is False:
        return False, "not in English"
    if eng is None:
        if not cfg["allow_unknown_language"]:
            return False, "language unknown"
        job.notes.append("language not checked")

    ok, why = filters.assess_experience(job, cfg["max_experience_years"],
                                        cfg["allow_unstated_experience"], cfg["include_internships"])
    job.notes.insert(0, why)
    if not ok:
        return False, f"experience: {why}"
    return True, "match"


def resolve_platform(company: dict, state: State, http: Http, cfg: dict, ref: date) -> tuple[str, str, str]:
    if company["ats"]:
        return company["ats"], company["ats_id"] or company["careers_url"], "set in companies.csv"
    cached = state.cached_ats(company["name"], ref, cfg["rediscover_after_days"])
    if cached:
        return cached[0], cached[1], "remembered"
    ats, ident, note = discover(company["careers_url"], http)
    state.remember_ats(company["name"], ats, ident, ref, True, note)
    return ats, ident, note


def match_record(job: Job, company: dict, ref: date) -> dict:
    return {
        "key": job.key(), "company": job.company, "title": job.title, "location": job.location,
        "posted": job.posted.isoformat() if job.posted else "",
        "date_is_first_seen": job.date_is_first_seen,
        "experience": job.notes[0] if job.notes else "",
        "notes": "; ".join(job.notes[1:]), "url": job.url, "source": job.source,
        "hq_country": company.get("country", ""), "sector": company.get("sector", ""),
        "found_on": ref.isoformat(),
    }


def process_company(company: dict, state: State, http: Http, ctx: Ctx, ref: date) -> tuple[dict, list]:
    cov = {"company": company["name"], "country": company.get("country", ""), "platform": "",
           "platform_id": "", "status": "ok", "jobs_read": 0, "title_matches": 0, "new_checked": 0,
           "new_matches": 0, "message": ""}
    matches = []
    reasons = Counter()
    started = time.monotonic()
    try:
        ats, ident, note = resolve_platform(company, state, http, ctx.cfg, ref)
        cov.update(platform=ats, platform_id=ident, message=note)
        reader = READERS.get(ats)
        if reader is None:
            raise ValueError(f"unknown platform '{ats}' in companies.csv")
        for job in reader(company["name"], ident, http, ctx):
            cov["jobs_read"] += 1
            if cov["jobs_read"] > MAX_JOBS_PER_COMPANY:
                break
            if not ctx.title_matches(job.title):
                continue
            cov["title_matches"] += 1
            key = job.key()
            if state.is_seen(key, ref):
                continue
            cov["new_checked"] += 1
            ok, reason = evaluate(job, ctx.cfg, ref, state.first_run)
            state.mark_seen(key, ref, job.title, job.company)
            reasons[reason] += 1
            if ok:
                matches.append(match_record(job, company, ref))
        if cov["jobs_read"] == 0 and ats == "generic":
            cov["status"] = "no jobs found"
            cov["message"] = "page may need a browser (JavaScript); add the platform in companies.csv"
    except Exception as e:  # one broken site must never stop the run
        cov["status"] = "error"
        cov["message"] = f"{type(e).__name__}: {str(e)[:160]}"
        if not company["ats"]:
            state.forget_ats(company["name"])   # rediscover next time
    cov["new_matches"] = len(matches)
    if reasons:
        cov["filtered_out"] = ", ".join(f"{r}: {n}" for r, n in reasons.most_common() if r != "match")
    cov["seconds"] = round(time.monotonic() - started, 1)
    return cov, matches


def run(only: list[str] | None = None, limit: int | None = None) -> dict:
    from . import report
    cfg = load_config()
    companies = load_companies()
    if only:
        wanted = {o.lower() for o in only}
        companies = [c for c in companies if c["name"].lower() in wanted]
    if limit:
        companies = companies[:limit]
    state = State(ROOT / "data")
    http = Http()
    ctx = Ctx(cfg=cfg, search_terms=cfg["search_terms"], titles=filters.compile_titles(cfg["title_patterns"]))
    ref = utc_today()
    started = datetime.now(timezone.utc)

    coverage, new_matches = [], []
    with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
        futures = {pool.submit(process_company, c, state, http, ctx, ref): c for c in companies}
        for fut in as_completed(futures):
            cov, matches = fut.result()
            coverage.append(cov)
            new_matches.extend(matches)
            flag = "!" if cov["status"] != "ok" else " "
            print(f"{flag} {cov['company'][:28]:28} {cov['platform'][:15]:15} read={cov['jobs_read']:<5} "
                  f"titles={cov['title_matches']:<4} new matches={cov['new_matches']} {cov['message'][:60]}",
                  flush=True)

    new_matches.sort(key=lambda m: (m["posted"], m["company"]), reverse=True)
    state.matches = new_matches + [m for m in state.matches
                                   if m["key"] not in {n["key"] for n in new_matches}]
    coverage.sort(key=lambda c: c["company"].lower())
    info = {"started": started, "finished": datetime.now(timezone.utc), "first_run": state.first_run,
            "companies": len(companies), "config": cfg}
    report.write_all(ROOT, new_matches, state.matches, coverage, info)
    state.save(ref, cfg["history_days"])
    print(f"\nDone: {len(new_matches)} new matching jobs from {len(companies)} companies.")
    return {"new": new_matches, "coverage": coverage}


def check_company(name: str) -> None:
    """Debug one company: show the detected platform and why each title-matching job passed or failed."""
    cfg = load_config()
    company = next((c for c in load_companies() if c["name"].lower() == name.lower()), None)
    if not company:
        raise SystemExit(f"'{name}' is not in companies.csv")
    http = Http()
    ctx = Ctx(cfg=cfg, search_terms=cfg["search_terms"], titles=filters.compile_titles(cfg["title_patterns"]))
    ref = utc_today()
    if company["ats"]:
        ats, ident, note = company["ats"], company["ats_id"] or company["careers_url"], "set in companies.csv"
    else:
        ats, ident, note = discover(company["careers_url"], http)
    print(f"{company['name']}: platform={ats} id={ident} ({note})")
    n = 0
    for job in READERS[ats](company["name"], ident, http, ctx):
        n += 1
        if not ctx.title_matches(job.title):
            continue
        ok, reason = evaluate(job, cfg, ref, first_run=False)
        print(f"  [{'MATCH' if ok else '  -  '}] {job.title[:60]:60} | {job.location[:30]:30} | "
              f"{job.posted} | {reason} | {'; '.join(job.notes)}")
    print(f"{n} jobs read in total.")
