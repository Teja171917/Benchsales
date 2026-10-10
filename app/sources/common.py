"""Shared helpers for job-source adapters."""
import time

import requests

UA = {"User-Agent": "BenchPilot/1.0 (staffing-tool; contact: recruiter@localhost)"}


def get(url, params=None, headers=None, timeout=30):
    h = dict(UA)
    if headers:
        h.update(headers)
    return requests.get(url, params=params, headers=h, timeout=timeout)


def clean(s):
    return (s or "").strip()


def strip_html(html: str) -> str:
    import re
    text = re.sub(r"<script.*?</script>", " ", html or "", flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|ul|ol|h[1-6]|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# ---- employment-type preference (steers API queries) ----
CONTRACT_TAGS = {"c2c", "w2", "contract", "1099", "c2h"}


def wanted_emp(settings: dict) -> list[str]:
    """Employment tags the recruiter wants, from the collect_emp_types setting."""
    from ..emptype import parse_wanted
    return parse_wanted(settings.get("collect_emp_types") or "")


# ---- small in-process cache for "download everything" endpoints ----
_CACHE: dict = {}


def get_json_cached(url: str, ttl: int = 300, **kw):
    """RemoteOK / Arbeitnow return their whole feed on every call; the
    collector asks once per search query, so cache the feed for a few minutes."""
    hit = _CACHE.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    r = get(url, **kw)
    r.raise_for_status()
    data = r.json()
    _CACHE[url] = (time.time(), data)
    return data
