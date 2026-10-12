from datetime import date

from jobbot import filters
from jobbot.models import Job
from jobbot.run import evaluate, load_config
from jobbot.textutil import parse_date

REF = date(2026, 10, 11)
EN = ("We are looking for a motivated person to join our team. You will work with the product team "
      "and our stakeholders to plan and deliver projects. This is a great opportunity for you to grow "
      "with us and learn how we build products for our customers in Europe and beyond. ")
DE = ("Wir suchen eine motivierte Person für unser Team. Du arbeitest mit dem Produktteam und unseren "
      "Partnern zusammen und bist für die Planung der Projekte zuständig. Wir bieten dir eine spannende "
      "Aufgabe mit vielen Möglichkeiten in einem wachsenden Unternehmen und freuen uns auf deine Bewerbung. ")


def job(**kw):
    base = dict(company="Acme", title="Junior Product Manager", url="https://x/1", source="t",
                location="Berlin, Germany", posted=date(2026, 10, 9), description=EN * 2, detail_loaded=True)
    base.update(kw)
    return Job(**base)


def cfg(**kw):
    c = load_config()
    c.update(kw)
    return c


def test_titles():
    t = filters.compile_titles(filters.DEFAULT_TITLE_PATTERNS)
    for ok in ["Project Manager", "Associate Project Manager", "Junior Product Manager (m/f/d)",
               "Product Coordinator", "Project Coordinator", "Programme Manager", "Business Analyst - Graduate",
               "Product Owner", "PMO Analyst"]:
        assert filters.title_matches(ok, t), ok
    for bad in ["Software Engineer", "Product Designer", "Sales Manager", "Data Analyst"]:
        assert not filters.title_matches(bad, t), bad


def test_location():
    assert filters.europe_status(job(location="Amsterdam")) is True
    assert filters.europe_status(job(location="Remote - EMEA")) is True
    assert filters.europe_status(job(location="New York, NY")) is False
    assert filters.europe_status(job(location="Cambridge, MA")) is False
    assert filters.europe_status(job(location="Bangalore, India")) is False
    assert filters.europe_status(job(location="London; New York")) is True
    assert filters.europe_status(job(location="", country_code="FR")) is True
    assert filters.europe_status(job(location="Walldorf, DE, 69190")) is True
    assert filters.europe_status(job(location="Remote", description="Open to candidates in the US only. " * 3)) is False
    assert filters.europe_status(job(location="Remote", description="Remote within Germany or Spain.")) is True
    assert filters.europe_status(job(location="Hybrid", description="nice to have " * 30)) is None


def test_language():
    assert filters.detect_language(EN * 2) == "en"
    assert filters.detect_language(DE * 2) == "de"
    assert filters.english_status(job(description="", language="")) is None


def test_years():
    assert filters.required_years("You have 3+ years of experience in product management.") == (3, None)
    assert filters.required_years("0-1 years of experience in a similar role") == (0, 1)
    assert filters.required_years("At least two years of professional experience") == (2, None)
    assert filters.required_years("Founded 25 years ago, we have experience in retail") is None
    assert filters.required_years("1-3 years experience; 5 years with SQL experience preferred") == (5, None)


def test_experience_decisions():
    ok, _ = filters.assess_experience(job(title="Senior Product Manager"))
    assert not ok
    ok, _ = filters.assess_experience(job(title="Product Manager Intern"))
    assert not ok
    ok, why = filters.assess_experience(job(title="Product Manager", description=EN + "3+ years of experience required."))
    assert not ok and "3+" in why
    ok, why = filters.assess_experience(job(title="Project Coordinator", description=EN))
    assert ok and why == "entry-level title"
    ok, why = filters.assess_experience(job(title="Product Manager", description=EN))
    assert not ok and why == "no entry-level signal"
    ok, why = filters.assess_experience(job(title="Product Manager", description=EN), allow_unstated=True)
    assert ok and why == "experience not stated"
    ok, why = filters.assess_experience(job(title="Product Manager", description=EN + " Ideal for recent graduates."))
    assert ok
    ok, _ = filters.assess_experience(job(title="Business Analyst", experience_level="entry"))
    assert ok
    ok, _ = filters.assess_experience(job(title="Project Manager", years_hint="lt-1"))
    assert ok


def test_dates():
    assert parse_date("Posted Today", REF) == REF
    assert parse_date("Posted Yesterday", REF) == date(2026, 10, 10)
    assert parse_date("Posted 3 Days Ago", REF) == date(2026, 10, 8)
    assert parse_date("Posted 30+ Days Ago", REF) == date(2026, 9, 11)
    assert parse_date(1760140800000) == date(2025, 10, 11)
    assert parse_date("2026-10-09T08:00:00Z") == date(2026, 10, 9)
    assert parse_date("Fri, 09 Oct 2026 10:00:00 GMT") == date(2026, 10, 9)
    assert parse_date("2026-10-09 10:00:00 UTC") == date(2026, 10, 9)


def test_evaluate_full():
    c = cfg()
    assert evaluate(job(), c, REF, False) == (True, "match")
    assert evaluate(job(posted=date(2026, 10, 1)), c, REF, False)[1] == "older than limit"
    assert evaluate(job(description=DE * 2), c, REF, False)[1] == "not in English"
    assert evaluate(job(location="Toronto, ON"), c, REF, False)[1] == "outside Europe"
    undated = job(posted=None)
    assert evaluate(undated, c, REF, True)[1] == "undated (first run)"
    undated = job(posted=None)
    assert evaluate(undated, c, REF, False)[0] and undated.date_is_first_seen


def test_detail_loaded_when_needed():
    calls = []

    def detail(j):
        calls.append(1)
        j.location = "Madrid, Spain"
        j.description = EN * 2

    j = job(title="Associate Product Manager", location="", description="", detail=detail, detail_loaded=False)
    assert evaluate(j, cfg(), REF, False) == (True, "match")
    assert calls == [1]
