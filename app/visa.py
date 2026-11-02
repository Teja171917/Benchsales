"""Work-authorization (visa) signals for jobs and consultants.

Two honest halves:

* classify_auth() reads a job description and returns the work-auth
  requirement the posting STATES, as a tag:
    citizens_only   — "US citizens only", security clearance, ...
    citizens_gc     — citizens and green-card holders (incl. ITAR
                      "US persons")
    no_sponsorship  — "no sponsorship", "will not sponsor", ...
    sponsorship_ok  — sponsorship offered / OPT welcome
    ""              — the posting says nothing usable (the majority)
  Only explicit wording counts; silence is never guessed at.

* status_key() normalises a consultant's free-text visa_status
  ("H1B", "Green Card", "Citizen", "STEM OPT EAD", ...) to a key,
  and compatible() says whether that consultant may take a job with
  a given tag: True / False, or None when either side is unknown.
"""
import re

CITIZENS_ONLY = "citizens_only"
CITIZENS_GC = "citizens_gc"
NO_SPONSORSHIP = "no_sponsorship"
SPONSORSHIP_OK = "sponsorship_ok"

AUTH_LABELS = {
    CITIZENS_ONLY: "US citizens only",
    CITIZENS_GC: "Citizens / Green Card",
    NO_SPONSORSHIP: "No sponsorship",
    SPONSORSHIP_OK: "Sponsorship OK",
}

# ordered most-restrictive first; the first family that matches wins
_RULES = [
    (CITIZENS_ONLY, [
        r"u\.?s\.? citizens? only",
        r"united states citizens? only",
        r"citizens? only\b",
        r"must be a(?:n)? (?:u\.?s\.?|us|united states) citizen",
        r"citizenship (?:is )?required",
        r"only (?:u\.?s\.?|us) citizens?",
        r"security clearance",
        r"secret clearance",
        r"top secret",
        r"ts/sci",
        r"dod clearance",
    ]),
    (CITIZENS_GC, [
        r"itar",
        r"u\.?s\.? persons?\b",
        r"citizens? (?:and|or|/) (?:green card|permanent resident)",
        r"(?:green card|permanent resident)[^.\n]{0,40}citizens?",
        r"citizens? (?:and|or) gc\b",
        r"gc (?:and|or) citizens?",
        r"u\.?s\.? citizens? (?:and|or) (?:gc|green card)",
    ]),
    (NO_SPONSORSHIP, [
        r"no (?:visa )?sponsorship",
        r"not (?:be )?(?:able to )?sponsor",
        r"will not (?:be able to )?sponsor",
        r"unable to sponsor",
        r"cannot sponsor",
        r"can'?t sponsor",
        r"without (?:employer )?sponsorship",
        r"sponsorship (?:is )?not (?:available|offered|provided)",
        r"do(?:es)? not (?:offer|provide) sponsorship",
        r"no c2c sponsorship",  # rare phrasing, still a refusal
        r"must be authorized to work[^.\n]{0,80}without sponsorship",
        r"authorized to work[^.\n]{0,60}no sponsorship",
    ]),
    (SPONSORSHIP_OK, [
        r"sponsorship (?:is )?(?:available|offered|provided)",
        r"visa sponsorship available",
        r"will sponsor",
        r"we sponsor",
        r"sponsor (?:h-?1b|visa)",
        r"h-?1b (?:sponsorship|transfer)",
        r"h1b sponsorship",
        r"open to (?:opt|cpt|h-?1b)",
        r"(?:opt|cpt) (?:candidates )?(?:welcome|accepted|eligible)",
        r"accepting (?:opt|cpt|h-?1b)",
        r"stem opt",
    ]),
]
_COMPILED = [(tag, [re.compile(p) for p in pats]) for tag, pats in _RULES]


def classify_auth(text: str) -> str:
    """The work-auth tag a posting states, or "" when it says nothing
    we can stand behind."""
    t = (text or "").lower()
    if not t.strip():
        return ""
    for tag, pats in _COMPILED:
        if any(p.search(t) for p in pats):
            return tag
    return ""


def status_key(visa_status: str) -> str:
    """Normalise free-text consultant visa status to a key:
    citizen / green_card / h1b / h4_ead / opt_ead / other_ead /
    tn / other / ""
    """
    t = (visa_status or "").strip().lower()
    if not t:
        return ""
    if "citizen" in t or t == "usc" or "u.s. citizen" in t:
        return "citizen"
    if "green card" in t or "permanent resident" in t or "lpr" in t \
            or re.search(r"\bgc\b", t):
        return "green_card"
    if "opt" in t or "cpt" in t or "f-1" in t or "f1" in t:
        return "opt_ead"
    if "h1b" in t or "h-1b" in t or "h 1b" in t:
        return "h1b"
    if "h4" in t or "h-4" in t:
        return "h4_ead"
    if "ead" in t:
        return "other_ead"
    if re.search(r"\btn\b", t):
        return "tn"
    return "other"


# consultant status -> job tags it may take (unknown tags "" always ok)
_ALLOWED = {
    "citizen": {CITIZENS_ONLY, CITIZENS_GC, NO_SPONSORSHIP, SPONSORSHIP_OK},
    "green_card": {CITIZENS_GC, NO_SPONSORSHIP, SPONSORSHIP_OK},
    # H-1B and OPT both need an employer willing to sponsor (now or
    # when the EAD runs out), so a stated no-sponsorship bar excludes
    # them; TN is employer-specific in the same way.
    "h1b": {SPONSORSHIP_OK},
    "opt_ead": {SPONSORSHIP_OK},
    "tn": {SPONSORSHIP_OK},
    # an EAD holder who needs no sponsorship (H4/L2/GC EAD, ...)
    "h4_ead": {NO_SPONSORSHIP, SPONSORSHIP_OK},
    "other_ead": {NO_SPONSORSHIP, SPONSORSHIP_OK},
}


def compatible(consultant_visa_text: str, auth_tag: str):
    """True when the consultant may take the job, False on a clear
    conflict, None when either side is unstated/unknown."""
    key = status_key(consultant_visa_text)
    if not key or key == "other" or not auth_tag:
        return None
    allowed = _ALLOWED.get(key)
    if allowed is None:
        return None
    return auth_tag in allowed
