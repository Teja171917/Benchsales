"""URL import: recruiter pastes any job posting URL (LinkedIn, Indeed, Dice,
company career page); we fetch it and extract title/company/description.
This is the v1 path for boards that block scraping."""
import ipaddress
import re
import socket
import uuid
from urllib.parse import urljoin, urlparse

import requests

from .common import UA, clean

NAME = "urlimport"
LABEL = "URL import (manual)"


def _fallback_text(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _assert_public(url: str) -> None:
    """Block server-side requests to private / loopback / link-local hosts
    (SSRF): when the app is hosted for a team, a pasted URL must not be able
    to reach the host's internal network or cloud-metadata endpoint."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http(s) URLs are allowed")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except socket.gaierror:
        raise ValueError(f"cannot resolve host: {parts.hostname}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError("that address is not a public website")


def _fetch(url: str, max_hops: int = 5) -> requests.Response:
    """GET with manual redirects so every hop is checked by _assert_public."""
    for _ in range(max_hops + 1):
        _assert_public(url)
        resp = requests.get(url, headers=UA, timeout=30, allow_redirects=False)
        if resp.is_redirect and resp.headers.get("location"):
            url = urljoin(url, resp.headers["location"])
            continue
        resp.raise_for_status()
        return resp
    raise ValueError("too many redirects")


def import_url(url: str) -> dict:
    url = (url or "").strip()
    if not url:
        raise ValueError("URL is required")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url  # tolerate pasted links without a scheme
    resp = _fetch(url)
    html = resp.text

    text = ""
    try:
        import trafilatura
        dl = trafilatura.extract(html, include_comments=False,
                                 include_tables=True)
        if dl:
            text = dl.strip()
    except Exception:
        pass
    if not text:
        text = _fallback_text(html)

    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        title = clean(re.sub(r"\s+", " ", m.group(1)))[:200]

    company = ""
    for pat in (r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
                r'"hiringOrganization"[^}]*"name"\s*:\s*"([^"]+)',
                r'"company"[^}]{0,80}?"name"\s*:\s*"([^"]+)'):
        mm = re.search(pat, html, re.I)
        if mm:
            company = clean(mm.group(1))
            break

    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    return {
        "source": NAME,
        "source_id": f"url-{uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:12]}",
        "title": title or f"Posting from {host}",
        "company": company,
        "location": "",
        "remote_flag": "remote" in text[:2000].lower(),
        "url": url,
        "description": text[:60000],
        "posted_at": "",
        "salary": "",
        "employment_type": "",
    }
