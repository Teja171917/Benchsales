"""Shared helpers for job-source adapters."""
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
