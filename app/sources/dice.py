"""Dice jobs through Dice's own official connector (free).

In June 2026 Dice (DHI Group) launched an MCP server - an "LLM connector" -
at https://mcp.dice.com/mcp so AI assistants can search Dice's tech jobs.
It is listed as open (no key). This adapter talks to it the same way an AI
assistant does (JSON-RPC over HTTP):

  initialize -> tools/list -> tools/call <the search tool>

The exact names of the search tool's inputs and of the fields in its answer
were not published, so both are read at run time: the tool's own input
schema says which parameters exist, and the answer is searched for a list of
job-like records. If Dice answers in a shape this code does not understand,
the error shows the first part of the answer so the code can be adjusted.

Turn off with the setting dice_enabled = "0".
"""
import json
import re

import requests

from .common import clean, wanted_emp, CONTRACT_TAGS

NAME = "dice"
LABEL = "Dice (official connector)"
URL = "https://mcp.dice.com/mcp"
PROTOCOL = "2025-06-18"
REMOTE_WORDS = {"remote", "anywhere", "worldwide", "usa", "us", "united states",
                "work from home", "wfh", ""}


def enabled(settings: dict) -> bool:
    return (settings.get("dice_enabled") or "1") != "0"


# ---------------------------------------------------------------- transport
class _Session:
    def __init__(self, timeout: int = 40):
        self.s = requests.Session()
        self.s.headers.update({"Content-Type": "application/json",
                               "Accept": "application/json, text/event-stream",
                               "User-Agent": "BenchPilot/1.0"})
        self.timeout = timeout
        self.n = 0

    def _post(self, payload: dict):
        r = self.s.post(URL, data=json.dumps(payload), timeout=self.timeout)
        sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        if sid:
            self.s.headers["Mcp-Session-Id"] = sid
        if r.status_code in (401, 403):
            raise RuntimeError(f"Dice connector refused the request (HTTP {r.status_code}) - "
                               "it may need a sign-in now")
        r.raise_for_status()
        return r

    def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        r = self._post({"jsonrpc": "2.0", "id": self.n, "method": method,
                        "params": params or {}})
        msg = _parse_rpc(r.text, r.headers.get("Content-Type", ""), self.n)
        if "error" in msg:
            raise RuntimeError(f"Dice connector error: {str(msg['error'])[:200]}")
        return msg.get("result") or {}

    def notify(self, method: str):
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": {}})
        except Exception:
            pass


def _parse_rpc(text: str, ctype: str, want_id: int) -> dict:
    """The answer is plain JSON or a server-sent-events stream of JSON."""
    candidates = []
    if "event-stream" in ctype or text.lstrip().startswith(("event:", "data:")):
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    candidates.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
    else:
        try:
            data = json.loads(text)
            candidates = data if isinstance(data, list) else [data]
        except ValueError:
            pass
    for c in candidates:
        if isinstance(c, dict) and c.get("id") == want_id:
            return c
    for c in candidates:
        if isinstance(c, dict) and ("result" in c or "error" in c):
            return c
    raise RuntimeError("Dice connector answered in an unexpected format: " + text[:200])


# ------------------------------------------------------------ input mapping
def _pick(props: dict, names: list) -> str | None:
    low = {k.lower(): k for k in props}
    for n in names:
        if n in low:
            return low[n]
    for n in names:
        for k_low, k in low.items():
            if n in k_low:
                return k
    return None


def _enum(schema: dict) -> list:
    if not isinstance(schema, dict):
        return []
    if schema.get("enum"):
        return list(schema["enum"])
    items = schema.get("items")
    if isinstance(items, dict) and items.get("enum"):
        return list(items["enum"])
    for alt in schema.get("anyOf") or schema.get("oneOf") or []:
        e = _enum(alt)
        if e:
            return e
    return []


def _is_array(schema: dict) -> bool:
    if not isinstance(schema, dict):
        return False
    if schema.get("type") == "array":
        return True
    return any(isinstance(a, dict) and a.get("type") == "array"
               for a in schema.get("anyOf") or schema.get("oneOf") or [])


def _choose(options: list, wanted_words: list) -> list:
    out = []
    for o in options:
        s = str(o).lower().replace("-", "_").replace(" ", "_")
        if any(w in s for w in wanted_words):
            out.append(o)
    return out


def build_args(schema: dict, query: dict, settings: dict) -> dict:
    """Fill the search tool's own parameters from our query."""
    props = (schema or {}).get("properties") or {}
    args: dict = {}
    title = (query.get("title") or "").strip()
    loc = (query.get("location") or "").strip()
    remote = loc.lower() in REMOTE_WORDS

    k = _pick(props, ["keyword", "keywords", "query", "q", "search", "searchterm",
                      "search_term", "title", "job_title", "role"])
    if not k:   # first required text field
        for name in (schema or {}).get("required") or []:
            if (props.get(name) or {}).get("type") in (None, "string"):
                k = name
                break
    if k:
        args[k] = title

    lk = _pick(props, ["location", "city", "where", "place"])
    if lk and not remote and lk != k:
        args[lk] = loc

    wk = _pick(props, ["workplace_types", "workplacetypes", "workplace_type",
                       "workplacetype", "workplace", "remote"])
    if wk and remote:
        opts = _enum(props[wk])
        if (props[wk] or {}).get("type") == "boolean":
            args[wk] = True
        elif opts:
            hit = _choose(opts, ["remote"])
            if hit:
                args[wk] = hit if _is_array(props[wk]) else hit[0]
        else:
            args[wk] = ["Remote"] if _is_array(props[wk]) else "Remote"

    ek = _pick(props, ["employment_types", "employmenttypes", "employment_type",
                       "employmenttype", "employment", "job_type", "jobtype"])
    if ek:
        want = wanted_emp(settings)
        words = []
        if "fulltime" in want:
            words += ["full"]
        if set(want) & CONTRACT_TAGS:
            words += ["contract", "third", "c2c", "corp"]
        opts = _enum(props[ek])
        if opts and words:
            hit = _choose(opts, words)
            if hit:
                args[ek] = hit if _is_array(props[ek]) else hit[0]

    pk = _pick(props, ["posted_date", "posteddate", "date_posted", "dateposted", "posted"])
    if pk:
        opts = _enum(props[pk])
        hit = _choose(opts, ["seven", "7", "week"]) if opts else []
        if hit:
            args[pk] = hit[0]

    sk = _pick(props, ["page_size", "pagesize", "limit", "max_results", "num_results",
                       "count", "size", "per_page"])
    if sk and (props[sk] or {}).get("type") in ("integer", "number"):
        mx = (props[sk] or {}).get("maximum") or 50
        args[sk] = int(min(50, mx))
    return args


# ----------------------------------------------------------- output mapping
_TITLE = ["title", "jobtitle", "job_title", "name"]


def _first(d: dict, keys: list):
    low = {k.lower(): k for k in d}
    for k in keys:
        if k in low and d[low[k]] not in (None, "", [], {}):
            return d[low[k]]
    return None


def _as_text(v) -> str:
    if isinstance(v, dict):
        return clean(str(_first(v, ["name", "displayname", "display_name", "text",
                                    "label", "city"]) or ""))
    if isinstance(v, list):
        return ", ".join(_as_text(x) for x in v if x)
    return clean(str(v)) if v is not None else ""


def _find_jobs(obj, depth: int = 0) -> list:
    """The first list of dicts that look like jobs (have a title)."""
    if depth > 6:
        return []
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if dicts and sum(1 for x in dicts if _first(x, _TITLE)) >= max(1, len(dicts) // 2):
            return dicts
        for x in obj:
            got = _find_jobs(x, depth + 1)
            if got:
                return got
    elif isinstance(obj, dict):
        for key in ("data", "jobs", "results", "hits", "items", "listings", "jobPostings"):
            if key in obj:
                got = _find_jobs(obj[key], depth + 1)
                if got:
                    return got
        for v in obj.values():
            got = _find_jobs(v, depth + 1)
            if got:
                return got
    return []


def to_job(d: dict) -> dict | None:
    title = _as_text(_first(d, _TITLE))
    if not title:
        return None
    url = _as_text(_first(d, ["detailspageurl", "details_page_url", "url", "joburl",
                              "job_url", "link", "applyurl", "apply_url"]))
    jid = _as_text(_first(d, ["id", "guid", "jobid", "job_id", "uuid"])) or url or title
    loc = _first(d, ["location", "joblocation", "job_location", "locations"])
    loc_txt = _as_text(loc)
    if not loc_txt:
        loc_txt = ", ".join(x for x in (_as_text(_first(d, ["city"])),
                                        _as_text(_first(d, ["state"]))) if x)
    wp = " ".join(str(x) for x in [_first(d, ["workplacetypes", "workplace_types",
                                              "workplacetype", "workplace_type"]) or ""]).lower()
    remote = bool(_first(d, ["isremote", "is_remote", "remote"]) is True
                  or "remote" in wp or "remote" in loc_txt.lower())
    if url and url.startswith("/"):
        url = "https://www.dice.com" + url
    if not url and re.fullmatch(r"[0-9a-fA-F\-]{16,}", jid or ""):
        url = f"https://www.dice.com/job-detail/{jid}"
    return {
        "source": NAME,
        "source_id": jid,
        "title": title,
        "company": _as_text(_first(d, ["companyname", "company_name", "company",
                                       "employer", "employername"])),
        "location": loc_txt or ("Remote" if remote else ""),
        "remote_flag": remote,
        "url": url,
        "description": _as_text(_first(d, ["description", "summary", "snippet",
                                           "jobdescription", "job_description"])),
        "posted_at": _as_text(_first(d, ["posteddate", "posted_date", "dateposted",
                                         "date_posted", "posted", "createddate"])),
        "salary": _as_text(_first(d, ["salary", "pay", "compensation"])),
        "employment_type": _as_text(_first(d, ["employmenttype", "employment_type",
                                               "employmenttypes", "jobtype"])),
    }


def parse_result(result: dict) -> list[dict]:
    payload = result.get("structuredContent")
    if payload is None:
        texts = [c.get("text", "") for c in result.get("content") or []
                 if isinstance(c, dict) and c.get("type") == "text"]
        joined = "\n".join(texts).strip()
        try:
            payload = json.loads(joined)
        except ValueError:
            m = re.search(r"(\{.*\}|\[.*\])", joined, flags=re.S)
            try:
                payload = json.loads(m.group(1)) if m else None
            except ValueError:
                payload = None
        if payload is None:
            if not joined:
                return []
            raise RuntimeError("Dice connector answered in an unexpected format: "
                               + joined[:200])
    jobs, seen = [], set()
    for d in _find_jobs(payload):
        j = to_job(d)
        if j and j["source_id"] not in seen:
            seen.add(j["source_id"])
            jobs.append(j)
    return jobs


# ------------------------------------------------------------------- fetch
def fetch(query: dict, settings: dict) -> list[dict]:
    sess = _Session()
    sess.call("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                             "clientInfo": {"name": "BenchPilot", "version": "1.0"}})
    sess.notify("notifications/initialized")
    tools = sess.call("tools/list").get("tools") or []
    tool = next((t for t in tools if "search" in (t.get("name") or "").lower()), None)
    if not tool:
        raise RuntimeError("Dice connector has no search tool (tools: "
                           + ", ".join(t.get("name", "?") for t in tools)[:150] + ")")
    args = build_args(tool.get("inputSchema") or {}, query, settings)
    result = sess.call("tools/call", {"name": tool["name"], "arguments": args})
    if result.get("isError"):
        texts = " ".join(c.get("text", "") for c in result.get("content") or []
                         if isinstance(c, dict))
        raise RuntimeError("Dice search failed: " + texts[:200])
    return parse_result(result)
