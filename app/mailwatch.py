"""Application-confirmation detection from a connected inbox.

Applications are submitted on the portals' own sites, so BenchPilot never
sees them happen — the only trace is the confirmation email in the
applicant's inbox (RSATECH tester feedback, Nov 3 2026: "I applied and got
a confirmation email, but BenchPilot shows no applied notification").

A workspace can connect ONE inbox over IMAP (Settings → Application
inbox). A background poller reads new mail read-only, detects confirmation
messages, and flips the matching Queued card to Applied. The rules are
deliberately strict:

- a message must carry a clear confirmation phrase and NO rejection
  wording;
- a card flips only when exactly one queued application matches the
  extracted job title (+ company / applicant name) — ambiguity is logged
  for a human, never guessed;
- email bodies are never stored; only the detection event is logged.
"""
import imaplib
import re
from email import policy
from email.parser import BytesParser

from . import db

# ---------------------------------------------------------------- detection

_POSITIVE = [
    r"application (?:was |has been )?(?:sent|submitted|received|complete)",
    r"you(?:'ve| have) applied",
    r"you applied (?:for|to)",
    r"thank(?:s| you) for applying",
    r"application successfully submitted",
    r"successfully applied",
    r"your application (?:for|to|was|has)",
    r"we (?:have )?received your application",
    r"application confirmation",
]
_POSITIVE_RX = re.compile("|".join(f"(?:{p})" for p in _POSITIVE), re.I)

_NEGATIVE_RX = re.compile(
    r"not (?:be )?(?:selected|moving forward)|unfortunately|we regret|"
    r"position (?:has been )?filled|no longer (?:being )?considered|"
    r"decided to (?:move forward with other|pursue other)|"
    r"interview (?:invitation|request|scheduled)", re.I)

_PORTALS = [
    ("Dice", re.compile(r"dice\.com", re.I)),
    ("Indeed", re.compile(r"indeed\.com", re.I)),
    ("LinkedIn", re.compile(r"linkedin\.com", re.I)),
    ("Monster", re.compile(r"monster\.com", re.I)),
    ("ZipRecruiter", re.compile(r"ziprecruiter\.com", re.I)),
    ("Glassdoor", re.compile(r"glassdoor", re.I)),
    ("SmartRecruiters", re.compile(r"smartrecruiters", re.I)),
    ("Greenhouse", re.compile(r"greenhouse\.io", re.I)),
    ("Lever", re.compile(r"lever\.co", re.I)),
    ("Workable", re.compile(r"workable\.com", re.I)),
    ("Ashby", re.compile(r"ashbyhq\.com", re.I)),
]

_SUBJ_PATTERNS = [
    re.compile(r"application (?:for|to) (.+?) at (.+?)(?: was| has| —| -|$)", re.I),
    re.compile(r"you applied (?:for|to) (.+?) at (.+?)(?:\.|!|$)", re.I),
    re.compile(r"applied (?:for|to):?\s*(.+?)\s*(?:at|@|\|)\s*(.+?)$", re.I),
    re.compile(r"application submitted:?\s*(.+?)\s*(?:—|-|at)\s*(.+?)$", re.I),
    re.compile(r"your application (?:was sent to|has been submitted to) (.+?)$", re.I),
]
_BODY_PATTERNS = [
    re.compile(r"^(?:job title|position|role|title)\s*[:\-]\s*(.+)$", re.I | re.M),
    re.compile(r"you applied for (?:the )?(?:position of )?(.+?) at ([^.\n]+)", re.I),
    re.compile(r"application for (?:the )?(.+?) (?:position )?at ([^.\n]+)", re.I),
]
_COMPANY_PATTERNS = [
    re.compile(r"^(?:company|employer|organization)\s*[:\-]\s*(.+)$", re.I | re.M),
]
_DEAR = re.compile(r"^(?:dear|hi|hello)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*[,!]", re.M)


def _portal_of(sender: str) -> str:
    for name, rx in _PORTALS:
        if rx.search(sender or ""):
            return name
    return ""


def parse_confirmation(subject: str, body: str, sender: str) -> dict | None:
    """A confirmation event {portal, title, company, applicant} or None.
    Title/company are best-effort extractions; an empty title means the
    message confirms *an* application but cannot be matched to a card."""
    text = f"{subject or ''}\n{body or ''}"
    if not _POSITIVE_RX.search(text):
        return None
    if _NEGATIVE_RX.search(text):
        return None
    det = {"portal": _portal_of(sender), "title": "", "company": "",
           "applicant": ""}
    for rx in _SUBJ_PATTERNS:
        m = rx.search(subject or "")
        if m:
            if m.lastindex and m.lastindex >= 2:
                det["title"], det["company"] = m.group(1).strip(), m.group(2).strip()
            else:
                det["company"] = m.group(1).strip()
            break
    if not det["title"]:
        for rx in _BODY_PATTERNS:
            m = rx.search(body or "")
            if m:
                det["title"] = m.group(1).strip()
                if m.lastindex and m.lastindex >= 2 and not det["company"]:
                    det["company"] = m.group(2).strip()
                break
    if not det["company"]:
        for rx in _COMPANY_PATTERNS:
            m = rx.search(body or "")
            if m:
                det["company"] = m.group(1).strip()
                break
    m = _DEAR.search(body or "")
    if m:
        det["applicant"] = m.group(1).strip()
    return det


# ----------------------------------------------------------------- matching

_STOP = {"the", "a", "an", "of", "for", "and", "or", "in", "at", "with",
         "senior", "sr", "junior", "jr", "lead", "principal", "staff",
         "remote", "hybrid", "onsite", "on", "site"}


def _tokens(text: str) -> set:
    return {t for t in re.split(r"[^a-z0-9+#.]+", (text or "").lower())
            if t and t not in _STOP and len(t) > 1}


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def find_application(apps: list, det: dict) -> dict | None:
    """The one queued application a confirmation belongs to, or None.

    Strong = title overlap >= 0.6 and (company overlap >= 0.5, or the
    applicant name matches the consultant). Exactly one strong candidate
    flips; zero or several means a human decides."""
    if not det.get("title"):
        return None
    strong = []
    for a in apps:
        if a.get("status") != "queued":
            continue
        t = _overlap(det["title"], a.get("job_title") or "")
        if t < 0.6:
            continue
        c = _overlap(det["company"], a.get("company") or "") \
            if det.get("company") else 0.0
        name_hit = bool(det.get("applicant")) and \
            _overlap(det["applicant"], a.get("consultant_name") or "") >= 0.5
        if c >= 0.5 or name_hit or not det.get("company"):
            strong.append((t + c, a))
    if len(strong) == 1:
        return strong[0][1]
    if len(strong) > 1:
        # disambiguate by applicant name when it separates them cleanly
        named = [a for _, a in strong if det.get("applicant") and
                 _overlap(det["applicant"], a.get("consultant_name") or "") >= 0.5]
        if len(named) == 1:
            return named[0]
    return None


# ------------------------------------------------------------------- imap

def _message_text(raw: bytes) -> tuple[str, str, str]:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = str(msg.get("Subject") or "")
    sender = str(msg.get("From") or "")
    body = ""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            body = part.get_content() or ""
    except Exception:
        body = ""
    if "<" in body and ">" in body:      # html fallback: strip tags crudely
        body = re.sub(r"<[^>]+>", " ", body)
    return subject, sender, body[:6000]


def test_connection(host: str, user: str, password: str) -> tuple[bool, str]:
    try:
        with imaplib.IMAP4_SSL(host, timeout=20) as imap:
            imap.login(user, password)
            typ, _ = imap.select("INBOX", readonly=True)
            if typ != "OK":
                return False, "could not open INBOX"
        return True, "connected"
    except Exception as e:                       # surfaced to Settings as-is
        return False, str(e)[:200]


def poll_once() -> dict:
    """One poll of the current workspace's inbox (settings-gated).
    Returns counts {seen, confirmed, flipped, ambiguous}. Writes are one
    small commit per flip through the normal db helpers (WAL + busy
    timeout live in db.get_conn), so the poller never holds the write
    lock across network work."""
    out = {"seen": 0, "confirmed": 0, "flipped": 0, "ambiguous": 0}
    s = db.get_settings()
    if s.get("imap_enabled") != "1":
        return out
    host = s.get("imap_host") or "imap.gmail.com"
    user = s.get("imap_user") or ""
    password = s.get("imap_pass") or ""
    if not user or not password:
        return out
    last_uid = int(s.get("imap_last_uid") or 0)
    try:
        with imaplib.IMAP4_SSL(host, timeout=30) as imap:
            imap.login(user, password)
            imap.select("INBOX", readonly=True)
            if last_uid:
                typ, data = imap.uid("SEARCH", None, f"UID {last_uid + 1}:*")
            else:
                # first run: only the newest 100 messages (about the last
                # days), so a fresh connection doesn't scan years of mail
                typ, data = imap.uid("SEARCH", None, "ALL")
            uids = [int(u) for u in (data[0].split() if data and data[0] else [])]
            if not last_uid:
                uids = sorted(uids)[-100:]
            queued = None
            for uid in sorted(uids)[:100]:
                typ, fetched = imap.uid(
                    "FETCH", str(uid),
                    "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.8000>)")
                raw = b""
                for item in fetched or []:
                    if isinstance(item, tuple):
                        raw += item[1] or b""
                if not raw:
                    continue
                out["seen"] += 1
                subject, sender, body = _message_text(raw)
                det = parse_confirmation(subject, body, sender)
                last_uid = max(last_uid, uid)
                if det is None:
                    continue
                out["confirmed"] += 1
                if queued is None:
                    queued = db.list_applications("queued")
                app_row = find_application(queued, det)
                where = det["portal"] or "email"
                if app_row:
                    db.update_application(app_row["id"], "applied", None)
                    queued = [a for a in queued if a["id"] != app_row["id"]]
                    db.log_activity(
                        "applied_detected",
                        f"Marked Applied from a {where} confirmation email: "
                        f"{app_row['consultant_name']} — "
                        f"{app_row['job_title']} at {app_row['company']}",
                        actor="mailwatch")
                    out["flipped"] += 1
                elif det.get("title"):
                    db.log_activity(
                        "applied_unmatched",
                        f"{where} confirmation seen for “{det['title']}”"
                        f"{' at ' + det['company'] if det['company'] else ''} "
                        f"but no single queued card matched — left for the "
                        f"team to mark", actor="mailwatch")
                    out["ambiguous"] += 1
            db.set_setting("imap_last_uid", str(last_uid))
            db.set_setting("imap_last_error", "")
    except Exception as e:
        db.set_setting("imap_last_error", str(e)[:200])
    db.set_setting("imap_last_check", db.now_iso())
    return out
