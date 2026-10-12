"""The five filters: job title, Europe location, English, 0-1 years of experience, recency."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .models import Job

# ----------------------------------------------------------------------------- titles
DEFAULT_TITLE_PATTERNS = [
    r"\bproject\s+(manager|coordinator|officer|administrator|analyst|management\s+(associate|analyst|trainee))\b",
    r"\bproduct\s+(manager|owner|coordinator|management\s+(associate|analyst|trainee))\b",
    r"\bprogram(me)?\s+(manager|coordinator|associate|analyst)\b",
    r"\bbusiness\s+analyst\b",
    r"\bpmo\s+(analyst|coordinator|associate|officer|specialist)\b",
    r"\b(associate|junior|jr\.?)\s+(project|product|program(me)?)\s+manager\b",
]


def compile_titles(patterns) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]


def title_matches(title: str, compiled) -> bool:
    return any(p.search(title or "") for p in compiled)


# ----------------------------------------------------------------------------- location
EUROPE_COUNTRIES = {
    "AL": ["albania"], "AD": ["andorra"], "AT": ["austria", "österreich"], "BY": ["belarus"],
    "BE": ["belgium", "belgië", "belgique"], "BA": ["bosnia"], "BG": ["bulgaria"],
    "HR": ["croatia", "hrvatska"], "CY": ["cyprus"], "CZ": ["czech", "czechia", "česko"],
    "DK": ["denmark", "danmark"], "EE": ["estonia", "eesti"], "FI": ["finland", "suomi"],
    "FR": ["france"], "DE": ["germany", "deutschland"], "GR": ["greece", "hellas"],
    "HU": ["hungary", "magyarország"], "IS": ["iceland"], "IE": ["ireland", "éire"],
    "IT": ["italy", "italia"], "XK": ["kosovo"], "LV": ["latvia"], "LI": ["liechtenstein"],
    "LT": ["lithuania", "lietuva"], "LU": ["luxembourg"], "MT": ["malta"], "MD": ["moldova"],
    "MC": ["monaco"], "ME": ["montenegro"], "NL": ["netherlands", "nederland", "holland"],
    "MK": ["north macedonia", "macedonia"], "NO": ["norway", "norge"], "PL": ["poland", "polska"],
    "PT": ["portugal"], "RO": ["romania", "românia"], "SM": ["san marino"], "RS": ["serbia"],
    "SK": ["slovakia"], "SI": ["slovenia"], "ES": ["spain", "españa"], "SE": ["sweden", "sverige"],
    "CH": ["switzerland", "schweiz", "suisse", "svizzera"], "UA": ["ukraine"],
    "GB": ["united kingdom", "england", "scotland", "wales", "northern ireland", "great britain"],
    "UK": [],
}
EUROPE_CODES = set(EUROPE_COUNTRIES)

EUROPE_CITIES = """
london manchester birmingham edinburgh glasgow leeds bristol cambridge oxford reading belfast cardiff newcastle
liverpool sheffield nottingham brighton milton keynes slough guildford
dublin cork galway limerick
paris lyon marseille toulouse lille bordeaux nantes nice strasbourg montpellier rennes grenoble sophia antipolis
la défense la defense courbevoie issy-les-moulineaux boulogne-billancourt clermont-ferrand
berlin munich münchen hamburg frankfurt cologne köln düsseldorf stuttgart leipzig dresden hanover hannover nuremberg
nürnberg bonn essen dortmund mannheim karlsruhe heidelberg walldorf wolfsburg ingolstadt erlangen darmstadt
bremen freiburg augsburg regensburg potsdam
amsterdam rotterdam the hague den haag utrecht eindhoven delft leiden groningen hoofddorp amstelveen veldhoven
brussels bruxelles brussel antwerp antwerpen ghent gent leuven liège mechelen
luxembourg zurich zürich geneva genève basel bern lausanne zug lugano winterthur
vienna wien graz linz salzburg innsbruck
madrid barcelona valencia seville sevilla bilbao málaga malaga zaragoza
lisbon lisboa porto braga coimbra
milan milano rome roma turin torino florence firenze bologna naples napoli genoa genova verona padua padova
stockholm gothenburg göteborg malmö malmo uppsala lund linköping
copenhagen københavn aarhus odense aalborg billund
oslo bergen trondheim stavanger
helsinki espoo tampere turku oulu vantaa
warsaw warszawa kraków krakow wrocław wroclaw gdańsk gdansk poznań poznan łódź lodz katowice
prague praha brno ostrava
bratislava budapest debrecen bucharest bucurești cluj-napoca cluj iași iasi timișoara timisoara
sofia plovdiv varna athens athina thessaloniki
zagreb split ljubljana belgrade beograd novi sad sarajevo skopje tirana podgorica
tallinn tartu riga rīga vilnius kaunas
reykjavik valletta nicosia limassol kyiv kiev lviv chisinau minsk
""".split()
_MULTI_WORD_CITIES = ["milton keynes", "sophia antipolis", "la défense", "la defense", "the hague",
                      "den haag", "novi sad", "cluj-napoca"]

EUROPE_REGION = re.compile(
    r"\b(europe|european|emea|eu|eea|dach|nordics?|benelux|baltics?|cee|cet|cest|uk|"
    r"european union|remote\s*-\s*eu)\b", re.I)

NON_EUROPE = re.compile(
    r"\b(united states|usa|u\.s\.|america|canada|mexico|brazil|brasil|argentina|chile|colombia|peru|"
    r"india|china|japan|korea|singapore|malaysia|indonesia|philippines|vietnam|thailand|australia|"
    r"new zealand|israel|uae|united arab emirates|saudi|qatar|egypt|south africa|nigeria|kenya|morocco|"
    r"hong kong|taiwan|pakistan|bangladesh|turkey|türkiye|"
    r"new york|san francisco|seattle|boston|chicago|austin|los angeles|denver|atlanta|dallas|houston|"
    r"toronto|vancouver|montreal|bangalore|bengaluru|hyderabad|pune|chennai|mumbai|delhi|gurgaon|"
    r"gurugram|noida|shanghai|beijing|shenzhen|tokyo|seoul|sydney|melbourne|são paulo|sao paulo|"
    r"mexico city|buenos aires|dubai|abu dhabi|tel aviv|cairo|johannesburg|cape town|nairobi|lagos|"
    r"kuala lumpur|manila|jakarta|bangkok|istanbul|riyadh|doha|americas|apac|latam)\b", re.I)

# "Cambridge, MA", "Paris, TX", "London, ON" ... are not in Europe.
_US_CA_TWINS = re.compile(
    r"\b(cambridge|birmingham|london|paris|manchester|athens|dublin|rome|berlin|hamburg|vienna|"
    r"valencia|toledo|naples|florence|milan|bristol|oxford)\s*,\s*"
    r"(ma|al|on|tx|ga|oh|ca|ny|ky|nh|fl|il|ia|in|mi|va|pa|nj|ct|wi|sc|nc|tn|or|"
    r"massachusetts|alabama|ontario|texas|georgia|ohio|california|florida|new york)\b", re.I)


def _has_european_place(text: str, loose: bool = True) -> bool:
    """loose=False only accepts country names (safe for free text like descriptions)."""
    low = text.lower()
    for names in EUROPE_COUNTRIES.values():
        for n in names:
            if re.search(rf"\b{re.escape(n)}\b", low):
                return True
    if not loose:
        return False
    for c in _MULTI_WORD_CITIES:
        if c in low:
            return True
    words = set(re.findall(r"[\wäöüßéèêáàíóúñçøåæłńśźżčšžřőű'-]+", low))
    if words & set(EUROPE_CITIES):
        return True
    # ISO country codes written as ", DE" / "(DE)" / "DE-Berlin"
    for code in re.findall(r"(?:^|[\s,(/-])([A-Z]{2})(?=$|[\s,)/-])", text):
        if code in EUROPE_CODES:
            return True
    return False


def europe_status(job: Job) -> Optional[bool]:
    """True = Europe, False = clearly outside Europe, None = can't tell yet."""
    if job.country_code:
        if job.country_code.upper() in EUROPE_CODES:
            return True
        # one non-European code but maybe other European locations listed
    loc = _US_CA_TWINS.sub(" ", job.location or "")
    if loc and _has_european_place(loc):
        return True
    if loc and EUROPE_REGION.search(loc):
        return True
    if job.country_code and job.country_code.upper() not in EUROPE_CODES:
        return False
    if job.location and _US_CA_TWINS.search(job.location):
        return False
    if loc and NON_EUROPE.search(loc):
        return False
    if re.search(r"\bremote\b", loc, re.I) or job.remote:
        head = (job.description or "")[:3000]
        if EUROPE_REGION.search(head) or _has_european_place(head, loose=False):
            return True
        if head and (NON_EUROPE.search(head) or re.search(r"\bUS\b", head)):
            return False
        return None
    return None


# ----------------------------------------------------------------------------- language
_STOP = {
    "en": "the and to of in for with you our we are will is on as your be this that or an have".split(),
    "de": "und der die das wir sie mit für ist ein eine zu von auf den im bei du dich deine unsere werden".split(),
    "fr": "et le la les des vous nous de du pour avec une est en dans sur votre notre au aux".split(),
    "es": "y el la los las de para con una que en del por nuestro tu su como experiencia".split(),
    "it": "e il la le di per con una che del della nel siamo sei tua nostra degli".split(),
    "nl": "en de het een van voor met je wij jij zijn op ons onze bij naar ook".split(),
    "sv": "och att det som för med du vi är en av på har till våra din".split(),
    "pl": "i w na z do się jest dla oraz nas jako który twoje będzie".split(),
    "pt": "e o a os as de para com uma que em do da no na nosso você".split(),
}


def detect_language(text: str) -> str:
    words = re.findall(r"[a-zà-ÿąćęłńóśźżčšžřőű]+", (text or "").lower())[:1500]
    if len(words) < 25:
        return ""
    counts = {lang: 0 for lang in _STOP}
    sets = {lang: set(v) for lang, v in _STOP.items()}
    for w in words:
        for lang, s in sets.items():
            if w in s:
                counts[lang] += 1
    best = max(counts, key=counts.get)
    ranked = sorted(counts.values(), reverse=True)
    if ranked[0] < 5 or ranked[0] < ranked[1] * 1.3:
        return ""
    return best


def english_status(job: Job) -> Optional[bool]:
    if job.description:
        lang = detect_language(job.description)
        if lang:
            return lang == "en"
    if job.language:
        return job.language.lower() == "en"
    return None


# ----------------------------------------------------------------------------- experience
_NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a": 1, "an": 1}
_N = r"(\d{1,2}|zero|one|two|three|four|five|six|seven|eight|nine|ten)"
_YEARS_RX = [
    re.compile(rf"{_N}\s*\+?\s*(?:-|–|to)\s*{_N}\s*\+?\s*years?", re.I),                     # 1-3 years
    re.compile(rf"(?:at least|minimum(?: of)?|min\.?|more than|over|ideally|around)\s*{_N}\s*\+?\s*years?", re.I),
    re.compile(rf"{_N}\s*\+\s*years?", re.I),                                                # 3+ years
    re.compile(rf"{_N}\s*(?:or more\s*)?years?", re.I),                                      # 2 years
]

SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|lead|principal|head|director|staff|vp|vice president|chief|expert|"
    r"manager\s+(ii|iii|iv|2|3|4)|ii|iii|iv|experienced|group product manager)\b", re.I)
INTERN_TITLE = re.compile(
    r"\b(intern|internship|werkstudent|working student|praktikum|praktikant|stagiaire|stage|"
    r"thesis|apprentice(ship)?|ausbildung|trainee\s*-?\s*intern)\b", re.I)
ENTRY_TITLE = re.compile(
    r"\b(junior|jr\.?|associate|graduate|grad|entry|trainee|assistant|coordinator|apm|early career|"
    r"rotational|new grad)\b", re.I)
ENTRY_TEXT = re.compile(
    r"\b(entry[- ]level|no (prior |previous )?(professional )?experience (is )?(required|needed|necessary)|"
    r"recent(ly)? graduat|graduate programme|graduate program|early[- ]career|first (job|role) after|"
    r"0\s*(?:-|–|to)\s*[12]\s*years?|up to (one|1|two|2) years?|less than (one|1|two|2) years?|"
    r"career starter|berufseinsteiger)", re.I)


def _to_int(s: str) -> int:
    return int(s) if s.isdigit() else _NUM_WORDS.get(s.lower(), 99)


def required_years(text: str) -> Optional[tuple[int, Optional[int]]]:
    """Largest stated minimum near the word 'experience' (conservative), with its upper bound."""
    if not text:
        return None
    best: Optional[tuple[int, Optional[int]]] = None
    low = text.lower()
    taken = []
    for rx in _YEARS_RX:
        for m in rx.finditer(low):
            if any(a <= m.start() < b for a, b in taken):
                continue
            window = low[max(0, m.start() - 80): m.end() + 80]
            if "experienc" not in window and "erfahrung" not in window:
                continue
            if re.search(r"(years? (old|ago)|anniversary|founded|history|in business|since \d{4})", window):
                continue
            taken.append((m.start(), m.end()))
            lo = _to_int(m.group(1))
            hi = _to_int(m.group(2)) if m.lastindex and m.lastindex >= 2 else None
            if lo > 20:
                continue
            if best is None or lo > best[0]:
                best = (lo, hi)
    return best


def assess_experience(job: Job, max_years: int = 1, allow_unstated: bool = False,
                      include_internships: bool = False) -> tuple[bool, str]:
    title = job.title or ""
    if SENIOR_TITLE.search(title):
        return False, "senior title"
    if not include_internships and (INTERN_TITLE.search(title) or job.experience_level == "intern"):
        return False, "internship"
    if job.experience_level in ("mid", "senior"):
        return False, f"{job.experience_level} level"
    if job.months_required is not None:
        yrs = job.months_required / 12
        return (yrs <= max_years, f"requires ~{yrs:g} yrs")
    if job.years_hint:
        h = job.years_hint.lower()
        if h in ("lt-1", "0-1", "<1"):
            return True, "0-1 yrs"
        m = re.match(r"(\d+)", h)
        if m:
            return int(m.group(1)) <= max_years, f"{job.years_hint} yrs"
    yrs = required_years(job.description)
    if yrs:
        lo, hi = yrs
        label = f"{lo}-{hi} yrs" if hi is not None else f"{lo}+ yrs"
        return lo <= max_years, f"requires {label}"
    if job.experience_level == "entry":
        return True, "entry level"
    if ENTRY_TITLE.search(title):
        return True, "entry-level title"
    if ENTRY_TEXT.search(job.description or ""):
        return True, "entry-level wording"
    if allow_unstated:
        return True, "experience not stated"
    return False, "no entry-level signal"


# ----------------------------------------------------------------------------- recency
def age_days(job: Job, ref: date) -> Optional[int]:
    d = job.posted
    if d is None:
        return None
    return (ref - d).days
