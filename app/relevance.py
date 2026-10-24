"""Is a job title about what was searched? (used by live search)"""
import re

GENERIC_WORDS = {"engineer", "developer", "specialist", "analyst", "manager", "senior",
                 "sr", "lead", "junior", "jr", "consultant", "associate", "principal",
                 "staff", "remote", "job", "jobs", "the", "and", "of", "in", "for", "a"}
SAME_AS = {   # a word in the search also accepts these words in a job title
    "qa": {"qa", "quality", "test", "tester", "testing", "sdet", "qe"},
    "test": {"test", "tester", "testing", "qa", "sdet", "qe"},
    "tester": {"test", "tester", "testing", "qa", "sdet", "qe"},
    "testing": {"test", "tester", "testing", "qa", "sdet", "qe"},
    "sdet": {"sdet", "test", "testing", "qa"},
    "automation": {"automation", "automated", "automate"},
    "dev": {"dev", "developer", "development"},
    "frontend": {"frontend", "front", "front-end"},
    "backend": {"backend", "back", "back-end"},
}


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9+#.]+", (text or "").lower().replace("/", " ")))


def title_fits(query: str, job_title: str) -> bool:
    """Live search shows a job only when its TITLE is about what was searched:
    every important word of the search (or a word that means the same, e.g.
    QA = Test = SDET) must be in the job title. Generic words like "engineer"
    are not required. Boards such as RemoteOK return their whole feed, so
    without this a search for "QA Automation Engineer" showed front-end jobs."""
    q = [w for w in _words(query)]
    important = [w for w in q if w not in GENERIC_WORDS] or q
    t = _words(job_title)
    if "quality" in t and "assurance" in t:
        t |= {"qa"}
    return all(t & SAME_AS.get(w, {w}) for w in important)


