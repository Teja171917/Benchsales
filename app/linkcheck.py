"""Posting-link liveness for the Watchdog.

A link counts as DEAD only on confident evidence: HTTP 404/410, or a 200
page that says the job is gone ("position has been filled", "no longer
available", ...). Bot walls (403), timeouts, redirects we cannot follow
and every other failure are UNKNOWN — recruiters get told "couldn't
verify", never a false "dead". (Oct 31 2026 recon found roughly half the
top-match links already dead; the queue should not carry corpses.)
"""
import urllib.error
import urllib.request

DEAD_PHRASES = (
    "job not found", "position has been filled", "no longer available",
    "this job has expired", "posting has expired", "job is closed",
    "no longer accepting applications", "this position is no longer",
    "job posting has closed", "vacancy has been filled",
)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def classify(status: int, text: str) -> tuple[str, str]:
    """(verdict, evidence): verdict is alive | dead | unknown."""
    if status in (404, 410):
        return "dead", f"HTTP {status}"
    if status == 200:
        t = (text or "").lower()
        for p in DEAD_PHRASES:
            if p in t:
                return "dead", f"page says “{p}”"
        return "alive", "HTTP 200"
    return "unknown", f"HTTP {status}"


def check(url: str, timeout: int = 8) -> tuple[str, str]:
    if not url:
        return "unknown", "no link"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(60000).decode("utf-8", "ignore")
            return classify(r.status, body)
    except urllib.error.HTTPError as e:
        return classify(e.code, "")
    except Exception as e:
        return "unknown", str(e)[:60]
