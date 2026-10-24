"""Deep links into the big US job portals, pre-filled with the recruiter's
search (title, location, employment type, posted-within).

Why links instead of scraping: Dice has no public API, and Indeed / LinkedIn
block automated scraping and forbid it in their terms. Opening the portal
with the search already filled in — in the recruiter's own logged-in browser
— is the reliable, allowed path. Actual job *data* comes from the JSearch
(LinkedIn/Indeed/Glassdoor/ZipRecruiter via Google for Jobs) and Adzuna APIs.

Dice, Indeed and LinkedIn links carry employment-type and posted-date
filters using the parameter names those sites use in their own search URLs.
These could NOT be tested from the build environment (no access to the
portals), and portals change parameters without notice — worst case a portal
ignores a filter and shows the same query unfiltered. The other portals get
keyword + location only. Open each once and confirm before relying on it.
"""
from urllib.parse import quote_plus

PORTALS = [
    {"id": "dice", "label": "Dice", "home": "https://www.dice.com/",
     "note": "Best for C2C / W2 contract (tech). Sign in for contact details."},
    {"id": "linkedin", "label": "LinkedIn", "home": "https://www.linkedin.com/jobs/",
     "note": "Needs your LinkedIn login for full results."},
    {"id": "indeed", "label": "Indeed", "home": "https://www.indeed.com/",
     "note": "Largest volume; direct employers and agencies."},
    {"id": "glassdoor", "label": "Glassdoor", "home": "https://www.glassdoor.com/",
     "note": "Salary context alongside postings."},
    {"id": "monster", "label": "Monster", "home": "https://www.monster.com/",
     "note": "Older board, still carries contract roles."},
    {"id": "careerbuilder", "label": "CareerBuilder", "home": "https://www.careerbuilder.com/",
     "note": "Staffing-heavy listings."},
    {"id": "ziprecruiter", "label": "ZipRecruiter", "home": "https://www.ziprecruiter.com/",
     "note": "Many staffing-agency postings."},
    {"id": "lensa", "label": "Lensa", "home": "https://lensa.com/",
     "note": "US job search with many staffing postings."},
]

CONTRACT_TAGS = {"c2c", "w2", "contract", "1099", "c2h"}


def _kw(title: str, emp: list[str]) -> str:
    """Boards without a contract-type URL filter: add the staffing keywords."""
    words = []
    if "c2c" in emp:
        words.append("C2C")
    if "w2" in emp:
        words.append("W2")
    return title + (" (" + " OR ".join(words) + ")" if words else "")


def build_links(title: str, location: str = "", emp: list[str] | None = None,
                days: int = 7) -> list[dict]:
    """Return [{id, label, url, note}] for every portal."""
    emp = emp or []
    q = quote_plus(title.strip())
    if location.strip().lower().strip(".") in {"usa", "us", "u.s", "u.s.a", "united states",
                                               "united states of america", "america"}:
        location = ""          # whole country -> handled as United States below
    loc = quote_plus(location.strip())
    # Blank location: say "United States" - otherwise the portal guesses from
    # the visitor's IP address (e.g. Hyderabad, India).
    us_loc = loc or "United+States"
    contract = bool(set(emp) & CONTRACT_TAGS)
    fulltime = "fulltime" in emp

    # Dice: employmentType CONTRACTS / FULLTIME / THIRD_PARTY (third party = C2C vendors)
    dice_types = []
    if fulltime:
        dice_types.append("FULLTIME")
    if contract:
        dice_types += ["CONTRACTS", "THIRD_PARTY"]
    dice_posted = "ONE" if days <= 1 else ("THREE" if days <= 3 else ("SEVEN" if days <= 7 else ""))
    dice = (f"https://www.dice.com/jobs?q={q}&location={loc}&countryCode=US"
            + (f"&filters.postedDate={dice_posted}" if dice_posted else ""))
    if dice_types:   # Dice wants ONE parameter, values joined by "|" (%7C)
        dice += "&filters.employmentType=" + "%7C".join(dice_types)

    # Indeed: jt(fulltime) / jt(contract); fromage = days
    indeed_q = quote_plus(_kw(title.strip(), emp)) if contract else q
    indeed = f"https://www.indeed.com/jobs?q={indeed_q}&l={us_loc}&fromage={days}"
    if contract and not fulltime:
        indeed += "&sc=0kf%3Ajt%28contract%29%3B"
    elif fulltime and not contract:
        indeed += "&sc=0kf%3Ajt%28fulltime%29%3B"

    # LinkedIn: f_JT = F (full-time) / C (contract); f_TPR seconds
    li_types = []
    if fulltime:
        li_types.append("F")
    if contract:
        li_types.append("C")
    li = (f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(_kw(title.strip(), emp)) if contract else q}"
          f"&location={loc or 'United+States'}&f_TPR=r{days * 86400}")
    if li_types:
        li += "&f_JT=" + "%2C".join(li_types)

    # ZipRecruiter, Glassdoor, Monster, Lensa, CareerBuilder don't understand
    # "(C2C OR W2)" and return 0 jobs with it - plain title only.
    zip_ = (f"https://www.ziprecruiter.com/jobs-search?search={q}"
            f"&location={us_loc}")

    # Glassdoor sends Indian visitors to glassdoor.co.in unless the link names
    # the country itself: IN1 = United States in Glassdoor's own link format.
    if location.strip():
        glass = (f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}"
                 f"&locKeyword={loc}&locT=N&locId=1")
    else:
        kw = "-".join(title.strip().lower().split()) or "jobs"
        kw = "".join(ch for ch in kw if ch.isalnum() or ch == "-")
        glass = (f"https://www.glassdoor.com/Job/united-states-{kw}-jobs-"
                 f"SRCH_IL.0,13_IN1_KO14,{14 + len(kw)}.htm")

    monster = (f"https://www.monster.com/jobs/search?q={q}"
               f"&where={us_loc}")
    # CareerBuilder and Lensa ignore/reject search links: use a Google search
    # limited to their site (reliable, and keeps the results in the USA).
    def _site(domain):
        return ("https://www.google.com/search?q=" + quote_plus(
            f"site:{domain} {title.strip()} jobs {location.strip() or 'United States'}"))
    cb = _site("careerbuilder.com")
    google = (f"https://www.google.com/search?q={quote_plus(_kw(title.strip(), emp))}"
              f"+jobs+{loc}&ibp=htl;jobs")

    urls = {"dice": dice, "indeed": indeed, "linkedin": li, "ziprecruiter": zip_,
            "glassdoor": glass, "monster": monster, "careerbuilder": cb,
            "google": google,
            "lensa": _site("lensa.com")}
    return [{"id": p["id"], "label": p["label"], "url": urls[p["id"]],
             "note": p["note"]} for p in PORTALS]


def check_reachability(timeout: float = 8.0) -> list[dict]:
    """Can THIS SERVER open each portal's home page? (Browsers on the
    recruiter's machine are what matter for link-outs; this only tells you
    whether the server can reach them, e.g. for URL import.)
    Status codes 403/429 mean the portal is up but blocks automated clients."""
    import requests
    from .sources.common import UA
    out = []
    for p in PORTALS:
        row = {"id": p["id"], "label": p["label"], "home": p["home"]}
        try:
            r = requests.get(p["home"], headers={**UA, "Accept": "text/html"},
                             timeout=timeout, allow_redirects=True, stream=True)
            row["http_status"] = r.status_code
            r.close()
            if r.status_code < 400:
                row["state"] = "reachable"
            elif r.status_code in (401, 403, 429):
                row["state"] = "up, but blocks automated access (use link-out / JSearch)"
            else:
                row["state"] = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            row["state"] = f"unreachable from server: {type(e).__name__}"
            row["http_status"] = None
        out.append(row)
    return out
