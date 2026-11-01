"""Apply-assist: build a FILL PLAN for a match's external application.

For a given match this fetches the employer's application page, checks
the posting is still live, finds the application form, and maps every
field to the consultant's BenchPilot data. The result is a plan a
person reviews — BenchPilot never fills or submits anything itself:

- fields the data answers are shown with their values;
- a required field the data can't answer (a screening question, a work
  authorization question with no visa status on file, salary or years
  questions) is a BLOCKER — the plan stops there, exactly like the
  direct-apply pilot rules;
- a dead or login-walled posting is reported, not worked around.
"""
import re
from html.parser import HTMLParser

import requests

from . import db

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/126.0 Safari/537.36"}

_DEAD_MARKERS = (
    "no longer accepting", "position has been filled", "job has closed",
    "posting has expired", "no longer available", "this job is closed",
    "applications are closed", "job not found", "page not found",
    "this listing is no longer", "expired job",
)


def _fetch(url: str) -> dict:
    """One GET of the application page. Never raises."""
    try:
        r = requests.get(url, headers=_UA, timeout=25, allow_redirects=True)
        return {"http": r.status_code, "final_url": r.url,
                "html": r.text or "", "error": ""}
    except requests.RequestException as e:
        return {"http": None, "final_url": url, "html": "",
                "error": f"{type(e).__name__}"}


def _classify(page: dict, has_form: bool) -> tuple[str, str]:
    """(status, detail): live / dead / unknown from the fetched page."""
    if page["http"] is None:
        return "unknown", f"the page could not be fetched ({page['error']})"
    if page["http"] in (404, 410):
        return "dead", f"the posting page is gone (HTTP {page['http']})"
    if page["http"] >= 400:
        return "unknown", f"the page returned HTTP {page['http']} — it " \
                           "may need a login or block automated checks"
    text = re.sub(r"<[^>]+>", " ", page["html"]).lower()
    for marker in _DEAD_MARKERS:
        if marker in text:
            return "dead", f"the page says the posting is closed " \
                           f"(\"{marker}\")"
    if has_form:
        return "live", "posting page loads and has an application form"
    return "unknown", "the page loads but no application form was found" \
                      " — it may sit behind a login or a script-driven app"


class _FormParser(HTMLParser):
    """Collect forms and their fields, with label text where present."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self._form = None
        self._label_texts = {}     # input id -> label text (either order)
        self._label_for = None
        self._label_text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._form = {"action": a.get("action", ""), "fields": []}
            self.forms.append(self._form)
        elif tag == "label":
            self._label_for = a.get("for")
            self._label_text = []
        elif tag in ("input", "textarea", "select") and self._form is not None:
            f = {"tag": tag, "type": (a.get("type") or "text").lower(),
                 "name": a.get("name", ""), "id": a.get("id", ""),
                 "placeholder": a.get("placeholder", ""),
                 "aria": a.get("aria-label", ""),
                 "required": ("required" in a
                              or a.get("aria-required") == "true"),
                 "label": self._label_texts.get(a.get("id", ""), "")}
            self._form["fields"].append(f)

    def handle_data(self, data):
        if self._label_for is not None:
            self._label_text.append(data)

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "label" and self._label_for is not None:
            text = " ".join(self._label_text).strip()
            if text:
                self._label_texts[self._label_for] = text
                # the field may already exist (label after the input)
                for form in self.forms:
                    for f in form["fields"]:
                        if f["id"] == self._label_for and not f["label"]:
                            f["label"] = text
            self._label_for = None


def _pick_form(html: str) -> dict | None:
    """The most application-like form on the page (or None)."""
    parser = _FormParser()
    try:
        parser.feed(html)
    except Exception:                       # malformed pages: best effort
        pass
    best, best_score = None, -1
    for form in parser.forms:
        fields = form["fields"]
        if not fields:
            continue
        hay = " ".join((f["name"] + f["id"] + f["label"]).lower()
                     for f in fields)
        score = len(fields)
        if any(f["type"] == "file" for f in fields):
            score += 10                     # resume upload: strong signal
        if any(f["type"] == "email" for f in fields):
            score += 5
        if "resume" in hay or "apply" in hay or "applicant" in hay:
            score += 5
        if score > best_score:
            best, best_score = form, score
    if best is None:
        return None
    # application-form bar: a resume upload, an email field, or a fuller
    # form with a name field. Anything less is a search/newsletter box on
    # a listing page — the real form lives one click further out.
    fields = best["fields"]
    hay = " ".join((f["name"] + f["id"] + f["label"]).lower()
                   for f in fields)
    if any(f["type"] == "file" for f in fields) \
            or any(f["type"] == "email" for f in fields) \
            or (len(fields) >= 4 and "name" in hay):
        return best
    return None


def _name_parts(full: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"\s+", (full or "").strip()) if p]
    parts = [p for p in parts if len(p) > 1 or not p.endswith(".")]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def _map_field(f: dict, c: dict, match: dict,
               has_cover: bool) -> dict:
    """Classify one form field against the consultant's data."""
    hay = " ".join([f["name"], f["id"], f["placeholder"], f["aria"],
                    f["label"]]).lower().replace("_", " ").replace("-", " ")
    label = f["label"] or f["placeholder"] or f["name"] or f["id"] \
        or "(unlabeled field)"
    out = {"field": label, "required": bool(f["required"]),
           "value": "", "status": "skipped"}
    first, last = _name_parts(c.get("name", ""))

    def filled(value):
        out["value"], out["status"] = value, "filled"
        return out

    def unanswered(why):
        out["status"] = "unanswered" if f["required"] else "skipped"
        out["value"] = why
        return out

    if f["type"] == "file":
        if "cover" in hay:
            out["status"] = "upload"
            out["value"] = ("the cover letter saved in BenchPilot"
                            if has_cover else
                            "no cover letter saved — generate one in the "
                            "Tailor screen (optional on most forms)")
            out["required"] = bool(f["required"]) and not has_cover
            if out["required"]:
                out["status"] = "unanswered"
            return out
        out["status"] = "upload"
        out["value"] = ("the tailored resume for this match"
                        if match.get("_has_tailored")
                        else "the consultant's resume (tailor it first "
                             "for a stronger application)")
        return out
    if f["type"] in ("submit", "button", "hidden", "checkbox") \
            and "agree" not in hay and "consent" not in hay:
        return out                                  # buttons etc.: skip
    if "email" in hay or f["type"] == "email":
        return filled(c.get("email", "")) if c.get("email") \
            else unanswered("no email on the consultant's record")
    if "phone" in hay or "mobile" in hay or f["type"] == "tel":
        return filled(c.get("phone", "")) if c.get("phone") \
            else unanswered("no phone on the consultant's record")
    if "first name" in hay or "fname" in hay or hay.strip() == "first":
        return filled(first)
    if "last name" in hay or "lname" in hay or "surname" in hay:
        return filled(last)
    if "full name" in hay or "your name" in hay or hay.strip() == "name" \
            or "applicant name" in hay or "candidate name" in hay:
        return filled(c.get("name", ""))
    if "linkedin" in hay:
        return filled(c["linkedin_url"]) if c.get("linkedin_url") \
            else unanswered("no LinkedIn URL on the consultant's record")
    if "location" in hay or "city" in hay or "address" in hay:
        return filled(c["location"]) if c.get("location") \
            else unanswered("no location on the consultant's record")
    if "visa" in hay or "authoriz" in hay or "sponsor" in hay \
            or "eligible to work" in hay or "work permit" in hay:
        return filled(c["visa_status"]) if c.get("visa_status") \
            else unanswered("no visa / work-authorization status on the "
                            "consultant's record — a person must answer")
    if "cover" in hay and f["tag"] == "textarea":
        out["status"] = "upload"
        out["value"] = ("paste the cover letter saved in BenchPilot"
                        if has_cover else
                        "no cover letter saved — optional on most forms")
        return out
    # anything else: salary, years, dates, screening questions, essays —
    # the resume data does not answer these; never guess.
    return unanswered("a question the consultant's BenchPilot data "
                      "cannot answer — a person must answer")


def build_fill_plan(match: dict) -> dict:
    """The full plan for one match (fetches the posting page once)."""
    consultant = db.get_consultant(match["consultant_id"]) or {}
    tailored = db.get_tailored_for_match(match["id"])
    cover = db.get_cover_letter(match["id"])
    plan = {
        "match_id": match["id"],
        "consultant_name": consultant.get("name", ""),
        "job_title": match.get("job_title", ""),
        "company": match.get("company", ""),
        "url": match.get("url", ""),
        "has_tailored_resume": bool(tailored),
        "has_cover_letter": bool(cover),
        "liveness": "unknown", "liveness_detail": "",
        "fields": [], "blockers": [], "verdict": "unknown",
    }
    if not plan["url"]:
        plan["verdict"] = "no_url"
        plan["liveness_detail"] = "this job has no application link on file"
        return plan
    page = _fetch(plan["url"])
    form = _pick_form(page["html"]) if page["html"] else None
    status, detail = _classify(page, form is not None)
    plan["liveness"], plan["liveness_detail"] = status, detail
    if status != "live" or form is None:
        plan["verdict"] = status            # dead / unknown: stop here
        return plan
    m2 = dict(match)
    m2["_has_tailored"] = bool(tailored)
    plan["fields"] = [_map_field(f, consultant, m2, bool(cover))
                      for f in form["fields"]]
    plan["blockers"] = [f["field"] for f in plan["fields"]
                        if f["status"] == "unanswered" and f["required"]]
    plan["verdict"] = "blocked" if plan["blockers"] else "ready"
    return plan
