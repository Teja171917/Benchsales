"""Employment-type detection for the USA staffing market.

Job boards give employment type as free text ("full_time", "CONTRACTOR",
"Contract") or not at all, and staffing vendors put the real terms in the
description ("C2C or W2", "no corp-to-corp"). This module turns all of that
into a small, fixed set of tags that the API and UI can filter on.

Tags:
    fulltime   direct-hire / permanent / FTE
    contract   any contract or temp role
    c2c        corp-to-corp accepted
    w2         W2 (employee of the vendor) accepted
    1099       independent contractor accepted
    c2h        contract-to-hire
    parttime   part time

Negations are respected: "No C2C", "C2C not accepted", "W2 only" (which also
rules out c2c / 1099 unless they are explicitly allowed elsewhere).
"""
import re

# bump when classify() rules change: saved jobs are re-tagged once on next start
VERSION = 2

TAGS = ["fulltime", "c2c", "w2", "contract", "1099", "c2h", "parttime"]
TAG_LABELS = {
    "fulltime": "Full-time",
    "c2c": "C2C",
    "w2": "W2",
    "contract": "Contract",
    "1099": "1099",
    "c2h": "Contract-to-hire",
    "parttime": "Part-time",
}

_C2C = r"(?:c2c|c\s?2\s?c|corp[\s\-]*to[\s\-]*corp(?:oration)?|c\s?-\s?t\s?-\s?c)"
_W2 = r"(?:w\s?-?\s?2)"
_1099 = r"(?:1099)"
_C2H = (r"(?:contract[\s\-]*to[\s\-]*(?:hire|perm(?:anent)?)|c2h|"
        r"temp[\s\-]*to[\s\-]*(?:hire|perm(?:anent)?)|cth)")
_FT = (r"(?:full[\s\-_]?time|fulltime|permanent|direct[\s\-]*hire|\bfte\b|"
       r"\bperm\b)")
_CONTRACT = r"(?:\bcontract(?:or)?\b|\btemp(?:orary)?\b|freelance)"
_PT = r"(?:part[\s\-_]?time|parttime)"

_NEGATOR = re.compile(r"\b(?:no|not|without|non|cannot|can'?t|never)\b[\s\-]*", re.I)
_POSITIVE_BREAK = re.compile(r"\b(?:but|however|yes|accept\w*|welcome|ok|okay|open to)\b", re.I)
_NEG_AFTER = (r"^\W{0,3}(?:\w+\s+){0,2}"
              r"(?:not\s+(?:accepted|allowed|considered|available|eligible|open|an option|permitted)|"
              r"is\s+not|are\s+not|unavailable|isn'?t|aren'?t)")


def _negated_before(text: str, start: int) -> bool:
    """True if a negator ("no", "not", "without", "non-") governs the term at
    `start`: it sits in the same clause (no . ; : ! ? or newline between) and
    the words in between are just a list ("No third party/C2C or 1099" negates
    both C2C and 1099). A comma or a word like "but"/"accepted" ends the effect."""
    head = text[:start]
    cut = max(head.rfind(c) for c in ".;:!?\n")
    clause = head[cut + 1:]
    last = None
    for last in _NEGATOR.finditer(clause):
        pass
    if last is None:
        return False
    between = clause[last.end():]
    return (len(between) <= 40 and "," not in between
            and not _POSITIVE_BREAK.search(between))


def _mentions(pattern: str, text: str):
    """Yield (positive: bool) for each mention of pattern in text."""
    for m in re.finditer(pattern, text, re.I):
        after = text[m.end():m.end() + 40]
        neg = _negated_before(text, m.start()) or \
            bool(re.search(_NEG_AFTER, after, re.I))
        yield not neg


def _has(pattern: str, text: str) -> bool:
    return any(_mentions(pattern, text))


def classify(employment_type: str = "", title: str = "",
             description: str = "") -> list[str]:
    """Return the sorted list of employment tags for one job."""
    et = (employment_type or "").lower()
    # description first N chars is where vendors state terms; keep the cost bounded
    body = f"{title or ''}\n{(description or '')[:20000]}"
    text = f"{et}\n{body}".lower()
    tags: set[str] = set()

    # --- explicit staffing terms (title / description / type text) ---
    if _has(_C2C, text):
        tags.add("c2c")
    if _has(_W2, text):
        tags.add("w2")
    if _has(_1099, text):
        tags.add("1099")
    if _has(_C2H, text):
        tags.add("c2h")

    # "W2 only" / "only W2" -> W2, and rule out c2c / 1099 unless stated
    # positively on their own elsewhere (e.g. "W2 only. 1099 not accepted").
    w2_only = re.search(rf"{_W2}\s*(?:only|candidates only|employees only|"
                        rf"required|requirement|position only)|only\s+{_W2}", text, re.I)
    if w2_only:
        tags.add("w2")
        tags.discard("c2c")
        tags.discard("1099")
    c2c_only = re.search(rf"{_C2C}\s*(?:only)|only\s+{_C2C}", text, re.I)
    if c2c_only:
        tags.add("c2c")
        tags.discard("w2")

    # --- general type words ---
    # employment_type / title are reliable; description text is boilerplate-prone
    # ("benefits for full-time employees"), so only strong phrases count there.
    head = f"{et}\n{(title or '').lower()}"
    if _has(_FT, head) or re.search(
            r"full[\s\-_]?time\s+(?:position|role|opportunity|basis)|"
            r"direct[\s\-]*hire|permanent\s+(?:position|role|hire|employee)",
            text, re.I):
        tags.add("fulltime")
    if _has(_PT, head) or re.search(
            r"part[\s\-_]?time\s+(?:position|role|opportunity|basis)", text, re.I):
        tags.add("parttime")

    # W2 alone does not imply contract (W2 full-time jobs exist), but
    # C2C / 1099 / contract-to-hire always do.
    if tags & {"c2c", "1099", "c2h"} or _has(_CONTRACT, head) or re.search(
            r"\b(?:contract(?:or)?|temporary)\s+(?:position|role|opportunity|"
            r"basis|assignment|job|duration)|\b\d+\s*\+?\s*(?:month|mo)s?\s+contract|"
            r"long[\s\-]*term\s+contract|\bcontract\s*[-:]\s*\d", text, re.I):
        tags.add("contract")

    order = {t: i for i, t in enumerate(TAGS)}
    return sorted(tags, key=lambda t: order[t])


def to_db(tags: list[str]) -> str:
    """Store as ',c2c,w2,' so SQL LIKE '%,c2c,%' matches whole tags."""
    return ("," + ",".join(tags) + ",") if tags else ""


def from_db(s: str) -> list[str]:
    return [t for t in (s or "").split(",") if t]


def matches_filter(job_tags: list[str], wanted: list[str],
                   include_unspecified: bool = False) -> bool:
    """OR semantics: job passes if it has any wanted tag. A job with no tags
    passes only when include_unspecified is set. No wanted tags = no filter."""
    if not wanted:
        return True
    if not job_tags:
        return include_unspecified
    return bool(set(job_tags) & set(wanted))


def parse_wanted(s: str) -> list[str]:
    return [t for t in (s or "").lower().replace(" ", "").split(",") if t in TAGS]
