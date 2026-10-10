"""AI-checked resume reading.

The AI (any OpenAI-compatible model set in Settings) reads the top of a
resume and returns name, email, phone, city and job title. Then plain code -
not another AI - double-checks every field against the resume text itself.
A resume only gets "Needs a quick check" when a check fails, so a person
looks at the few the AI is unsure about.

The AI only READS. It never writes into the resume, and a value that is not
literally in the resume text is thrown away.

Without an AI key the same checks run on the rule-based reader
(app/contact.py), so more resumes are flagged instead.
"""
import json
import re

import requests

from . import contact as contact_mod

SYSTEM = """You read a resume and return the candidate's contact details.
Return ONLY a JSON object with these keys:
  name, email, phone, location, job_title, confidence
Rules:
- Copy values EXACTLY as written in the resume. Never guess or invent.
- Use "" for anything that is not clearly written in the resume.
- location is the candidate's own city and state (for example "Dallas, TX").
- job_title is the headline role under the name (for example "Senior QA Engineer").
- confidence is "high", "medium" or "low": how sure you are of name and email.
Output the JSON only, no other text."""

_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_TEXT_LIMIT = 6000      # contact details are at the top of a resume


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def ai_extract(text: str, settings: dict) -> dict | None:
    """Ask the configured model. Returns a dict, or None when no key is set or
    the call fails (the caller then relies on the rule-based reader)."""
    base = (settings.get("llm_base_url") or "").rstrip("/")
    key = settings.get("llm_api_key") or ""
    model = settings.get("llm_model") or ""
    if not (base and key and model):
        return None
    try:
        r = requests.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "temperature": 0, "max_tokens": 400,
                  "messages": [{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": text[:_TEXT_LIMIT]}]},
            timeout=60)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return {k: str(data.get(k) or "").strip() for k in
                ("name", "email", "phone", "location", "job_title", "confidence")}
    except Exception:
        return None


def _name_ok(name: str, text: str, allow_single: bool = False) -> bool:
    words = name.split()
    return ((2 if not allow_single else 1) <= len(words) <= 4 and len(name) <= 40
            and all(re.fullmatch(r"[A-Za-z][A-Za-z.'\-]*", w) for w in words)
            and _squash(name) in _squash(text[:_TEXT_LIMIT]))


def read_contact(text: str, filename: str, settings: dict) -> dict:
    """Returns {info, needs_check, notes, used_ai}. info has name, email,
    phone, location (same shape as contact.parse_contact)."""
    rules = contact_mod.parse_contact(text, filename)
    ai = ai_extract(text, settings)
    head = text[:_TEXT_LIMIT]
    notes: list[str] = []
    info = dict(rules)

    if ai:
        # every AI value must really be in the resume, else it is dropped
        if ai["email"] and _EMAIL.match(ai["email"]) and ai["email"].lower() in head.lower():
            if rules.get("email") and rules["email"].lower() != ai["email"].lower():
                notes.append("AI and the rule reader found different emails")
            info["email"] = ai["email"]
        if ai["name"] and _name_ok(ai["name"], text, allow_single=True):
            if _squash(rules.get("name")) not in ("", _squash(ai["name"])):
                notes.append(f"AI read the name as “{ai['name']}”, the rule reader as “{rules['name']}”")
            info["name"] = ai["name"]
        if ai["phone"] and 10 <= len(_digits(ai["phone"])) <= 15 \
                and _digits(ai["phone"]) in _digits(head):
            info["phone"] = ai["phone"]
        if ai["location"] and _squash(ai["location"]) in _squash(head):
            info["location"] = ai["location"]
        if ai.get("confidence", "").lower() == "low":
            notes.append("the AI said it was not sure")

    # the same checks on whatever we ended up with
    nm = info.get("name", "")
    if nm and len(nm.split()) == 1 and _name_ok(nm, text, allow_single=True):
        notes.append("only one name found (no last name) - please check")
    elif not _name_ok(nm, text):
        notes.append("the name could not be confirmed in the resume")
    if not _EMAIL.match(info.get("email", "") or ""):
        notes.append("no valid email found")
    if info.get("phone") and not 10 <= len(_digits(info["phone"])) <= 15:
        notes.append("the phone number looks wrong")
    # de-duplicate, keep order
    seen, uniq = set(), []
    for n in notes:
        if n and n not in seen:
            seen.add(n)
            uniq.append(n)
    return {"info": info, "needs_check": bool(uniq), "notes": uniq,
            "used_ai": ai is not None}
