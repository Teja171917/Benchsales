"""Read a person's name / email / phone / city from the top of a resume, so a
consultant can be created from the resume file alone."""
import re

from .skills import extract_skills
from .usa import STATE_ABBR_TO_NAME

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}")
_CITY_ST = re.compile(r"\b([A-Z][A-Za-z.\-]+(?: [A-Z][A-Za-z.\-]+){0,2}),\s*([A-Z]{2})\b")
_NOT_NAME = re.compile(
    r"resume|curriculum|vitae|\bcv\b|summary|profile|objective|skills|experience|"
    r"engineer|developer|analyst|architect|manager|tester|consultant|specialist|"
    r"administrator|lead|linkedin|github|http|www|\.com", re.I)


def _clean_name(s: str) -> str:
    s = _EMAIL.sub(" ", s)
    s = _PHONE.sub(" ", s)
    s = re.split(r"[|•·,;]", s)[0]
    s = re.sub(r"\s+", " ", s).strip(" -–—:")
    return s


def _looks_like_name(s: str) -> bool:
    words = s.split()
    return (2 <= len(words) <= 4 and len(s) <= 40
            and all(re.fullmatch(r"[A-Za-z][A-Za-z.'\-]*", w) for w in words)
            and not _NOT_NAME.search(s))


def _nice(name: str) -> str:
    # "SHARAN MURALI" -> "Sharan Murali"; leave mixed case alone
    return name.title() if name.isupper() or name.islower() else name


def name_from_filename(filename: str) -> str:
    base = re.sub(r"\.[A-Za-z0-9]+$", "", filename or "")
    base = re.sub(r"[_\-.()\d]+", " ", base)  # first: "_" counts as a letter for \b
    base = re.sub(r"(?i)\b(resume|cv|updated|final|new|latest)\b", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return _nice(base) if base else ""


def parse_contact(text: str, filename: str = "") -> dict:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:15]
    head = "\n".join(lines)
    m = _EMAIL.search(head)
    email = m.group(0) if m else ""
    m = _PHONE.search(head)
    phone = m.group(0).strip() if m else ""
    name = ""
    # the name sits above the first line with an email / phone number
    first_contact = next((i for i, ln in enumerate(lines[:8])
                          if _EMAIL.search(ln) or _PHONE.search(ln)), None)
    window = lines[:first_contact + 1] if first_contact is not None else lines[:6]
    for ln in window[:6]:
        cand = _clean_name(ln)
        if _looks_like_name(cand):
            name = _nice(cand)
            break
    if not name and first_contact is not None:
        # a one-word name on its own line right above the contact line
        # ("RAJESWARI" / "281-627-6787 | raji@mail.com")
        for ln in window[:first_contact][:4]:
            cand = _clean_name(ln)
            if (re.fullmatch(r"[A-Za-z][A-Za-z.'\-]{2,24}", cand)
                    and not _NOT_NAME.search(cand) and not extract_skills(cand)):
                name = _nice(cand)
                break
    if not name:
        for ln in lines[:6]:
            cand = _clean_name(ln)
            if _looks_like_name(cand):
                name = _nice(cand)
                break
    if not name:
        name = name_from_filename(filename)
    location = ""
    for ln in lines[:12]:
        for m in _CITY_ST.finditer(ln):
            if m.group(2) in STATE_ABBR_TO_NAME:
                location = f"{m.group(1)}, {m.group(2)}"
                break
        if location:
            break
    return {"name": name or "New consultant", "email": email, "phone": phone,
            "location": location}
