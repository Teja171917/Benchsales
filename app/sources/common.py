"""Shared helpers for job-source adapters."""
import time

import requests

UA = {"User-Agent": "BenchPilot/1.0 (staffing-tool; contact: recruiter@localhost)"}


def get(url, params=None, headers=None, timeout=30):
    h = dict(UA)
    if headers:
        h.update(headers)
    return requests.get(url, params=params, headers=h, timeout=timeout)


def safe_error(e) -> str:
    """Error text with secrets removed (a failed request puts the whole URL,
    including app_key / api keys, into the message)."""
    import re
    return re.sub(r"(?i)\b(app_id|app_key|api_key|apikey|key|token|secret)=[^&\s'\"]+",
                  r"\1=***", str(e))


def clean(s):
    # feeds occasionally hand back numbers (e.g. a unix timestamp) where a
    # string is expected; coerce instead of crashing the whole source
    if s is None:
        return ""
    return str(s).strip()


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


def parallel_map(fn, items, workers: int = 6) -> list:
    """Order-preserving thread pool for slow HTTP-bound adapter work
    (Nov 8 2026): the staffing feeds fetched firms one by one —
    SmartRecruiters' first call of a run measured ~175s and Phenom's
    ~45s, most of the collection's fetch phase. Pure HTTP + in-memory
    work only; nothing here touches the database, and each item's
    function is expected to fail soft on its own errors."""
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


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


def get_text_cached(url: str, ttl: int = 900, **kw):
    """HTML twin of get_json_cached: whole-page feeds (Phenom career
    sites) are re-asked once per search query, so cache the page text."""
    hit = _CACHE.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    r = get(url, **kw)
    r.raise_for_status()
    _CACHE[url] = (time.time(), r.text)
    return r.text
