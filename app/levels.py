"""Experience-level detection for job postings.

One fixed ladder, Entry-Level to Architect-Level, read from the posting
itself: the title first (vendors state seniority there), then the years of
experience the description asks for. A posting that states neither stays
unstated ('') rather than being guessed into the middle of the ladder.
"""
import re

LEVELS = ["intern", "entry", "mid", "senior", "lead", "principal", "architect"]

LABELS = {
    "intern": "Intern",
    "entry": "Entry-Level",
    "mid": "Mid-Level",
    "senior": "Senior",
    "lead": "Lead",
    "principal": "Principal",
    "architect": "Architect-Level",
}

# title signals, highest rung first so "Senior Architect" lands on architect
_TITLE_RULES = [
    ("architect", re.compile(r"\barchitect\b", re.I)),
    ("principal", re.compile(r"\bprincipal\b", re.I)),
    ("lead", re.compile(r"\blead\b", re.I)),
    ("senior", re.compile(r"\bsenior\b|\bsr\.?\s", re.I)),
    ("intern", re.compile(r"\bintern(?:ship)?\b|\btrainee\b", re.I)),
    ("entry", re.compile(r"\bjunior\b|\bjr\.?\s|\bentry[\s-]*level\b|"
                         r"\bnew\s+grad\b|\bassociate\b", re.I)),
]

_YEARS = re.compile(r"(\d{1,2})\s*(?:\+|(?:\s*[-–]\s*\d{1,2})?)\s*years?\b", re.I)


def _from_years(text: str) -> str:
    """Map the smallest stated requirement ('8-10 years' -> 8) to a rung.
    The minimum is what the posting actually demands of a candidate."""
    mins = [int(m.group(1)) for m in _YEARS.finditer(text or "")]
    if not mins:
        return ""
    y = min(mins)
    if y >= 13:
        return "principal"
    if y >= 10:
        return "lead"
    if y >= 6:
        return "senior"
    if y >= 3:
        return "mid"
    return "entry"


def classify_level(title: str = "", description: str = "") -> str:
    """The posting's experience level, or '' when it states none."""
    t = title or ""
    for level, rx in _TITLE_RULES:
        if rx.search(t):
            return level
    return _from_years(description or "")
