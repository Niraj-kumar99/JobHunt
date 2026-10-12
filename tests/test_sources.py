"""Each platform reader against a sample of that platform's real response shape (no network)."""
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from jobbot import run as runmod
from jobbot import sources
from jobbot.discover import detect_in_text, discover
from jobbot.filters import compile_titles, DEFAULT_TITLE_PATTERNS
from jobbot.run import Ctx

TODAY = runmod.utc_today()
D1 = (TODAY - timedelta(days=1)).isoformat()
EN = ("We are looking for a motivated person to join our team. You will work with the product team and our "
      "stakeholders to plan and deliver projects. This is a great opportunity for you to grow with us. ") * 2


class FakeResp:
    def __init__(self, body, url):
        self._body, self.url = body, url
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return self._body if not isinstance(self._body, str) else json.loads(self._body)


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes   # list of (substring, body)
        self.calls = []

    def _find(self, url):
        self.calls.append(url)
        for key, body in self.routes:
            if key in url:
                return body
        raise RuntimeError(f"404 {url}")

    def get(self, url, **kw):
        return FakeResp(self._find(url), url)

    def get_json(self, url, **kw):
        return self.get(url, **kw).json()

    def post_json(self, url, payload, **kw):
        return self._find(url + "#" + payload.get("searchText", "") + f"#{payload.get('offset', 0)}")


CTX = Ctx(cfg={}, search_terms=["product manager"], titles=compile_titles(DEFAULT_TITLE_PATTERNS))


def test_greenhouse():
    http = FakeHttp([("boards-api.greenhouse.io", {"jobs": [{
        "id": 1, "title": "Associate Product Manager", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "location": {"name": "Berlin, Germany"}, "first_published": D1 + "T08:00:00Z",
        "content": "&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;"}]})])
    jobs = list(sources.greenhouse("Acme", "acme", http, CTX))
    assert jobs[0].title == "Associate Product Manager" and jobs[0].description == "Hello & welcome"
    assert jobs[0].posted.isoformat() == D1


def test_lever_eu():
    http = FakeHttp([("api.eu.lever.co/v0/postings/acme", [{
        "id": "abc", "text": "Project Coordinator", "hostedUrl": "https://jobs.eu.lever.co/acme/abc",
        "categories": {"location": "Paris", "allLocations": ["Paris", "Lyon"]}, "country": "fr",
        "createdAt": 1760140800000, "descriptionPlain": "Desc", "lists": [{"text": "You", "content": "<li>SQL</li>"}]}])])
    j = list(sources.lever("Acme", "eu/acme", http, CTX))[0]
    assert j.location == "Paris; Lyon" and j.country_code == "FR" and "SQL" in j.description


def test_ashby():
    http = FakeHttp([("api.ashbyhq.com", {"jobs": [{
        "id": "x", "title": "Product Manager", "location": "Remote", "secondaryLocations": [{"location": "Madrid"}],
        "isRemote": True, "publishedAt": D1, "jobUrl": "https://jobs.ashbyhq.com/acme/x", "descriptionPlain": "Hi"}]})])
    j = list(sources.ashby("Acme", "acme", http, CTX))[0]
    assert j.location == "Remote; Madrid" and j.remote


def test_smartrecruiters_with_detail():
    http = FakeHttp([
        ("postings/123", {"postingUrl": "https://jobs.smartrecruiters.com/Acme/123",
                          "jobAd": {"sections": {"jobDescription": {"text": "<p>Plan things</p>"},
                                                 "qualifications": {"text": "<p>0-1 years experience</p>"}}}}),
        ("companies/Acme/postings", {"content": [{
            "id": "123", "name": "Junior Project Manager", "releasedDate": D1 + "T10:00:00.000Z",
            "location": {"city": "Milan", "country": "it", "remote": False, "fullLocation": "Milan, Italy"},
            "experienceLevel": {"id": "entry_level"}, "language": {"code": "en"}}]}),
    ])
    j = list(sources.smartrecruiters("Acme", "Acme", http, CTX))[0]
    assert j.experience_level == "entry" and j.country_code == "IT" and j.language == "en"
    j.load_detail()
    assert "0-1 years" in j.description


def test_workable():
    http = FakeHttp([("apply.workable.com/api/v1/widget/accounts/acme", {"jobs": [{
        "title": "Business Analyst", "shortcode": "AB12", "url": "https://apply.workable.com/acme/j/AB12",
        "published_on": D1, "experience": "Entry level", "telecommuting": False,
        "locations": [{"city": "Athens", "country": "Greece", "countryCode": "GR"}], "description": "<p>x</p>"}]})])
    j = list(sources.workable("Acme", "acme", http, CTX))[0]
    assert j.country_code == "GR" and j.experience_level == "entry"


def test_recruitee():
    http = FakeHttp([("acme.recruitee.com/api/offers", {"offers": [{
        "id": 9, "title": "Product Owner", "careers_url": "https://acme.recruitee.com/o/po", "city": "Utrecht",
        "country": "Netherlands", "country_code": "NL", "published_at": D1 + " 09:00:00 UTC",
        "description": "<p>a</p>", "requirements": "<p>b</p>", "experience_code": "mid_level"}]})])
    j = list(sources.recruitee("Acme", "acme", http, CTX))[0]
    assert j.experience_level == "mid" and j.posted.isoformat() == D1


def test_personio():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?><workzag-jobs><position><id>77</id><office>Munich</office>
    <additionalOffices><office>Berlin</office></additionalOffices><name>Project Manager</name>
    <jobDescriptions><jobDescription><name>Your tasks</name><value>&lt;p&gt;Coordinate&lt;/p&gt;</value></jobDescription></jobDescriptions>
    <seniority>entry-level</seniority><yearsOfExperience>lt-1</yearsOfExperience><createdAt>{D1}T10:00:00+00:00</createdAt>
    </position></workzag-jobs>"""
    http = FakeHttp([("acme.jobs.personio.de/xml", xml)])
    j = list(sources.personio("Acme", "acme", http, CTX))[0]
    assert j.location == "Munich; Berlin" and j.years_hint == "lt-1" and "Coordinate" in j.description
    assert j.url == "https://acme.jobs.personio.de/job/77?language=en"


def test_workday():
    http = FakeHttp([
        ("/wday/cxs/acme/External/jobs#product manager#0", {"total": 2, "jobPostings": [
            {"title": "Product Manager", "externalPath": "/job/Berlin/PM_R1", "locationsText": "2 Locations",
             "postedOn": "Posted Yesterday"},
            {"title": "Senior Engineer", "externalPath": "/job/Berlin/SE_R2", "locationsText": "Berlin",
             "postedOn": "Posted Today"}]}),
        ("/wday/cxs/acme/External/job/Berlin/PM_R1", {"jobPostingInfo": {
            "jobDescription": "<p>Hi</p>", "location": "Berlin", "additionalLocations": ["Vienna"],
            "startDate": D1, "externalUrl": "https://acme.wd3.myworkdayjobs.com/External/job/Berlin/PM_R1",
            "country": {"descriptor": "Germany"}}}),
    ])
    jobs = list(sources.workday("Acme", "acme.wd3.myworkdayjobs.com|acme|External", http, CTX))
    assert len(jobs) == 2 and jobs[0].location == ""     # "2 Locations" isn't a place
    jobs[0].load_detail()
    assert jobs[0].location == "Berlin; Vienna; Germany" and jobs[0].posted.isoformat() == D1


def test_successfactors_rss():
    rss = f"""<?xml version="1.0"?><rss><channel><item><title>Product Manager (Walldorf, DE, 69190)</title>
    <link>https://jobs.acme.com/job/Walldorf-PM/1/</link><description>{'word ' * 80}</description>
    <pubDate>{(TODAY - timedelta(days=2)).strftime('%a, %d %b %Y')} 10:00:00 GMT</pubDate></item></channel></rss>"""
    http = FakeHttp([("jobs.acme.com/services/rss/job", rss)])
    j = list(sources.successfactors("Acme", "jobs.acme.com", http, CTX))[0]
    assert j.title == "Product Manager" and j.location == "Walldorf, DE, 69190" and j.detail_loaded


def test_generic_jsonld_and_links():
    page = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@graph":[
    {"@type":"JobPosting","title":"Project Coordinator","datePosted":"%s","url":"https://acme.com/j/1",
     "jobLocation":{"@type":"Place","address":{"addressLocality":"Lisbon","addressCountry":"PT"}},
     "description":"<p>Hi</p>","experienceRequirements":{"monthsOfExperience":12}}]}</script></head></html>""" % D1
    http = FakeHttp([("acme.com/careers", page)])
    j = list(sources.generic("Acme", "https://acme.com/careers", http, CTX))[0]
    assert j.country_code == "PT" and j.months_required == 12

    links = '<html><body><a href="/jobs/42">Junior Product Manager</a><a href="/about">About us</a></body></html>'
    http = FakeHttp([("beta.com/jobs/42", "<html lang='en'><main><p>%s</p></main></html>" % EN),
                     ("beta.com/careers", links)])
    jobs = list(sources.generic("Beta", "https://beta.com/careers", http, CTX))
    assert [x.title for x in jobs] == ["Junior Product Manager"]
    jobs[0].load_detail()
    assert jobs[0].language == "en" and "motivated" in jobs[0].description


def test_detection():
    assert detect_in_text('<a href="https://boards.greenhouse.io/acmeco">') == ("greenhouse", "acmeco")
    assert detect_in_text('src="https://boards.greenhouse.io/embed/job_board?for=acme2"') == ("greenhouse", "acme2")
    assert detect_in_text("https://jobs.eu.lever.co/acme") == ("lever", "eu/acme")
    assert detect_in_text("https://siemens.wd3.myworkdayjobs.com/en-US/External/job/x") == \
        ("workday", "siemens.wd3.myworkdayjobs.com|siemens|External")
    assert detect_in_text("https://careers.smartrecruiters.com/BoschGroup") == ("smartrecruiters", "BoschGroup")
    assert detect_in_text("https://acme.jobs.personio.de/") == ("personio", "acme.jobs.personio.de")
    assert detect_in_text("nothing here") is None


def test_discover_follows_one_link():
    http = FakeHttp([
        ("acme.com/careers/search", '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'),
        ("acme.com/careers", '<html><a href="/careers/search">Search all jobs</a></html>'),
    ])
    assert discover("https://acme.com/careers", http)[:2] == ("greenhouse", "acme")


# ----------------------------------------------------------------------------- end to end
def test_end_to_end(tmp_path, monkeypatch):
    root = tmp_path / "bot"
    root.mkdir()
    shutil.copy(Path(runmod.ROOT) / "config.yaml", root / "config.yaml")
    (root / "companies.csv").write_text(
        "name,country,city,sector,careers_url,ats,ats_id\n"
        "Acme,Germany,Berlin,Software,https://acme.com/careers,,\n"
        "Broken,France,Paris,Retail,https://broken.example/careers,,\n", encoding="utf-8")
    old = (TODAY - timedelta(days=20)).isoformat()
    gh = {"jobs": [
        {"id": 1, "title": "Associate Product Manager", "absolute_url": "https://g/1", "location": {"name": "Berlin"},
         "first_published": D1, "content": EN},
        {"id": 2, "title": "Senior Product Manager", "absolute_url": "https://g/2", "location": {"name": "Berlin"},
         "first_published": D1, "content": EN},
        {"id": 3, "title": "Project Coordinator", "absolute_url": "https://g/3", "location": {"name": "Austin, TX"},
         "first_published": D1, "content": EN},
        {"id": 4, "title": "Junior Project Manager", "absolute_url": "https://g/4", "location": {"name": "Paris"},
         "first_published": old, "content": EN},
        {"id": 5, "title": "Software Engineer", "absolute_url": "https://g/5", "location": {"name": "Berlin"},
         "first_published": D1, "content": EN},
    ]}
    fake = FakeHttp([("boards-api.greenhouse.io/v1/boards/acme", gh),
                     ("acme.com/careers", '<a href="https://boards.greenhouse.io/acme">Jobs</a>')])
    monkeypatch.setattr(runmod, "ROOT", root)
    monkeypatch.setattr(runmod, "Http", lambda: fake)

    first = runmod.run()
    assert [m["title"] for m in first["new"]] == ["Associate Product Manager"]
    cov = {c["company"]: c for c in first["coverage"]}
    assert cov["Acme"]["platform"] == "greenhouse" and cov["Broken"]["status"] == "error"
    for f in ["data/seen_jobs.json", "data/ats_cache.json", "docs/index.html",
              "output/job_matches.xlsx", "output/new_matches.csv", "output/coverage.csv"]:
        assert (root / f).exists(), f
    assert "Associate Product Manager" in (root / "docs/index.html").read_text()

    # Second run: same jobs -> nothing new; a fresh posting appears -> only it is reported.
    gh["jobs"].append({"id": 6, "title": "Graduate Business Analyst", "absolute_url": "https://g/6",
                       "location": {"name": "Remote - Europe"}, "first_published": TODAY.isoformat(), "content": EN})
    second = runmod.run()
    assert [m["title"] for m in second["new"]] == ["Graduate Business Analyst"]
    html = (root / "docs/index.html").read_text()
    assert "Graduate Business Analyst" in html and "Associate Product Manager" in html   # history kept
    assert not any("acme.com/careers" in c for c in fake.calls[-3:])   # platform remembered, no rediscovery
