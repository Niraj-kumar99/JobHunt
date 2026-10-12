"""Remembers which jobs were already seen, which platform each company uses, and past matches."""
from __future__ import annotations

import json
import os
import threading
from datetime import date, timedelta
from pathlib import Path


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


class State:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.seen_path = data_dir / "seen_jobs.json"
        self.ats_path = data_dir / "ats_cache.json"
        self.matches_path = data_dir / "matches.json"
        self.first_run = not self.seen_path.exists()
        self.seen: dict = _load(self.seen_path, {})
        self.ats: dict = _load(self.ats_path, {})
        self.matches: list = _load(self.matches_path, [])
        self.lock = threading.Lock()

    # ---- seen jobs
    def is_seen(self, key: str, today: date) -> bool:
        with self.lock:
            entry = self.seen.get(key)
            if entry:
                entry["last_seen"] = today.isoformat()
                return True
            return False

    def mark_seen(self, key: str, today: date, title: str, company: str) -> None:
        with self.lock:
            self.seen[key] = {"first_seen": today.isoformat(), "last_seen": today.isoformat(),
                              "title": title[:120], "company": company}

    # ---- platform cache
    def cached_ats(self, company: str, today: date, max_age: int):
        entry = self.ats.get(company)
        if not entry or not entry.get("ok", True):
            return None
        if (today - date.fromisoformat(entry["checked"])).days > max_age:
            return None
        return entry["ats"], entry["id"]

    def remember_ats(self, company: str, ats: str, ident: str, today: date, ok: bool = True, note: str = ""):
        with self.lock:
            self.ats[company] = {"ats": ats, "id": ident, "checked": today.isoformat(), "ok": ok, "note": note}

    def forget_ats(self, company: str):
        with self.lock:
            self.ats.pop(company, None)

    # ---- persistence
    def save(self, today: date, history_days: int) -> None:
        cutoff = (today - timedelta(days=90)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v.get("last_seen", "") >= cutoff}
        hist_cut = (today - timedelta(days=history_days)).isoformat()
        self.matches = [m for m in self.matches if m.get("found_on", "") >= hist_cut]
        _save(self.seen_path, self.seen)
        _save(self.ats_path, self.ats)
        _save(self.matches_path, self.matches)
