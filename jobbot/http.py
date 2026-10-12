"""One shared HTTP session with retries, timeouts and a polite per-host delay."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class Http:
    def __init__(self, timeout: int = 25, min_interval: float = 0.6):
        self.timeout = timeout
        self.min_interval = min_interval
        self._local = threading.local()
        self._host_lock = threading.Lock()
        self._last_hit: dict[str, float] = {}

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            retry = Retry(total=2, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                          allowed_methods=("GET", "POST"))
            s.mount("https://", HTTPAdapter(max_retries=retry))
            s.mount("http://", HTTPAdapter(max_retries=retry))
            s.headers.update({"User-Agent": USER_AGENT,
                              "Accept-Language": "en-GB,en;q=0.9"})
            self._local.session = s
        return s

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._host_lock:
            wait = self._last_hit.get(host, 0) + self.min_interval - time.monotonic()
            self._last_hit[host] = time.monotonic() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, **kw) -> requests.Response:
        self._throttle(url)
        r = self.session.get(url, timeout=self.timeout, **kw)
        r.raise_for_status()
        return r

    def get_json(self, url: str, **kw):
        kw.setdefault("headers", {"Accept": "application/json"})
        return self.get(url, **kw).json()

    def post_json(self, url: str, payload: dict, **kw):
        self._throttle(url)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update(kw.pop("headers", {}))
        r = self.session.post(url, json=payload, timeout=self.timeout, headers=headers, **kw)
        r.raise_for_status()
        return r.json()
