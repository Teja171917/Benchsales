"""In-app chat assistant for the bench sales team.

Answers questions from THIS workspace's live data (consultants, matches,
apply queue) plus a short guide to how BenchPilot works. It runs on the
same OpenAI-compatible LLM settings the workspace already uses for resume
reading/tailoring (Settings -> llm_base_url / llm_api_key / llm_model).

Read-only by design: it explains and points, it never changes data, sends
email, or submits applications. Everything it can see comes from the
caller's own workspace database — the server routes each request to that
workspace before this module runs, so one company never sees another's
bench.
"""
import re

import requests

from . import db
from . import tailor as tailor_mod

SYSTEM = """You are the BenchPilot assistant, helping a bench sales /
recruiting team inside their own BenchPilot workspace.

Rules:
- Answer ONLY from the WORKSPACE DATA and APP GUIDE below. If the answer
  is not there, say you don't see it in this workspace and name the tab
  where the person can check (Overview, Consultants, Jobs, Matches,
  Apply Queue, Agent Office, Settings).
- Never invent numbers, names, companies, salaries, or jobs.
- Two actions run through the app itself when a request names them:
  tailoring a resume and queueing a tailored match. If such a request
  reaches you, it means a detail was missing (usually whose resume) —
  ask for it. You never submit applications to employers, send email,
  or change settings; for anything else, give the exact steps in the
  app instead.
- Keep answers short and plain — a few sentences or a short list. Use
  the names and numbers from the data exactly as written.
- This workspace's data is private to this company. Never mention other
  companies or workspaces.
"""

APP_GUIDE = """APP GUIDE:
- Match score: 70% skills + 20% job-title fit + 10% location fit, plus
  +5 when the posting is under 7 days old. Capped at 100.
- Matches tab: filter by consultant, minimum score, source, City, and
  Work type (Remote / Hybrid / On-site). A match at the tailor threshold
  or above is auto-queued with a tailored resume when that setting is on.
- Apply Queue: the team's apply list. "Queued" means ready for a
  recruiter to submit on the employer's site — BenchPilot does not
  submit applications by itself.
- Tailor resume: rewrites a copy of the consultant's resume for one job.
  Skills the person may not have are FLAGGED, never silently added — a
  person must confirm them.
- Consultants tab: add a consultant by uploading a resume; contact
  details are read from the resume automatically.
- Team accounts: workspace admins approve new signups from the Team
  accounts page (link at the bottom right). Pending signups show an
  amber "waiting for approval" pill.
- Signups: new team members sign up at /signup with the company ID and
  wait for an admin's approval before they can sign in.
- Agent Office: six agents (Scout, Tailor, Watchdog, Market Analyst,
  Outreach, Compliance) review the pipeline daily; their drafts always
  need a person to send or approve.
- Job collection runs automatically on the interval set in Settings;
  jobs are collected once and scored against every consultant.
- Actions you can trigger by asking here: "tailor <name>'s resume" (or
  "fix the resume for <job>") tailors that consultant's resume for
  their best matching job; then "queue it" adds it to the Apply Queue
  with the tailored resume attached. Skills flagged as not in the
  original resume are never added without a person confirming them in
  the Tailor screen.
"""


def build_snapshot() -> str:
    """A compact text picture of this workspace, small enough to ride in
    every chat prompt."""
    settings = db.get_settings()
    consultants = db.list_consultants()
    summary = db.matches_summary(top_n=8)
    with db.get_conn() as conn:
        per_consultant = {r["consultant_id"]: (r["n"], r["best"]) for r in conn.execute(
            'SELECT consultant_id, COUNT(*) AS n, MAX(score) AS best '
            'FROM "matches" GROUP BY consultant_id')}
        queue = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM applications GROUP BY status")}
    lines = ["WORKSPACE DATA:"]
    lines.append(f"Consultants on the bench: {len(consultants)}")
    for c in consultants:
        n, best = per_consultant.get(c["id"], (0, None))
        lines.append(
            f"- {c['name']}"
            + (f" ({c['location']})" if c.get("location") else "")
            + f": {n} matches"
            + (f", best score {best}" if best is not None else "")
            + ("" if c.get("has_resume") else ", NO RESUME uploaded"))
    lines.append(f"Jobs in the pool: {db.count_jobs()}")
    lines.append(f"Total matches: {summary['total']}")
    if summary["top"]:
        lines.append("Top matches right now:")
        for m in summary["top"]:
            lines.append(
                f"- {m['job_title']} at {m['company']} — score {m['score']} "
                f"for {m['consultant_name']}"
                + (f", {m['salary']}" if m.get("salary") else ""))
    active = sum(n for s, n in queue.items()
                 if s not in ("rejected", "withdrawn"))
    lines.append(f"Apply queue: {active} active"
                 + (f" ({', '.join(f'{s}: {n}' for s, n in sorted(queue.items()))})"
                    if queue else ""))
    emp = (settings.get("collect_emp_types") or "").strip()
    if emp:
        lines.append(f"Job types collected: {emp}")
    lines.append(f"Match threshold: {settings.get('match_threshold', '60')}")
    lines.append("Auto-queue tailored matches: "
                 + ("on" if settings.get("auto_queue_tailored") == "1" else "off"))
    return "\n".join(lines)


def _call_llm(settings: dict, messages: list) -> str | None:
    """One chat-completions call on the workspace's configured model.
    Returns the reply text, or None when no model is configured or the
    call fails."""
    base = (settings.get("llm_base_url") or "").rstrip("/")
    key = settings.get("llm_api_key") or ""
    model = settings.get("llm_model") or ""
    if not (base and key and model):
        return None
    try:
        r = requests.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "temperature": 0.2, "max_tokens": 700,
                  "messages": messages},
            timeout=60)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception:
        return None


_NO_AI = ("I can help with this workspace's consultants, matches and "
          "apply queue — but the AI isn't switched on for this workspace "
          "yet, so I can't chat properly. An admin can turn it on in "
          "Settings by adding the AI base URL, API key and model (the "
          "same ones used for resume tailoring). Until then: Matches "
          "shows each consultant's scored jobs, and the Apply Queue is "
          "the team's apply list.")


# ---------------- actions (deterministic, no model involved) ----------------

_last_action: dict = {}   # (db path, actor) -> {match_id, tailored_id, ...}

_TAILOR_WORDS = re.compile(
    r"\b(tailor|fix|improve|update|rewrite|maximi[sz]e|polish)\b", re.I)
_QUEUE_WORDS = re.compile(r"\bqueue\b", re.I)


def _run_tailor(match: dict) -> dict:
    """The same tailor run the Tailor screen performs."""
    result = tailor_mod.tailor_match(match, db.get_settings())
    tid = db.insert_tailored(match["id"], result["text"],
                             result["tailored_by"],
                             result["added_skills_flagged"])
    return {"id": tid, "tailored_by": result["tailored_by"],
            "added_skills_flagged": result["added_skills_flagged"]}


def _find_consultant(text: str, consultants: list) -> dict | None:
    """Match a consultant by any distinctive part of their name — people
    say "Abhinava" or "Seetha", not always the full roster name. The
    consultant with the most name tokens present wins."""
    low = " " + re.sub(r"[^a-z0-9 ]", " ", text.lower()) + " "
    best, best_hits = None, 0
    for c in consultants:
        tokens = [t for t in re.split(r"[^a-z0-9]+",
                                      (c.get("name") or "").lower())
                  if len(t) >= 3]
        hits = sum(1 for t in tokens if f" {t} " in low)
        if hits > best_hits:
            best, best_hits = c, hits
    return best


def _try_action(message: str, actor: str) -> dict | None:
    """Run a tailor/queue action when the message asks for one.
    Returns a chat reply dict, or None to fall through to the model."""
    key = (str(db.current_path()), actor or "shared")
    text = message.strip()
    # queue follow-up ("queue it") after a tailor action
    if _QUEUE_WORDS.search(text) and key in _last_action:
        last = _last_action.pop(key)
        db.queue_application(last["match_id"], last["tailored_id"])
        return {"reply":
                f"Queued — {last['consultant_name']} for "
                f"{last['job_title']} at {last['company']} is now in the "
                f"Apply Queue with the tailored resume attached. Nothing "
                f"has been submitted to the employer; it is on the team's "
                f"apply list.", "ai": False,
                "action": {"type": "queued", "match_id": last["match_id"]}}
    # tailor request
    if _TAILOR_WORDS.search(text) and ("resume" in text.lower()
                                      or "cv" in text.lower()):
        consultants = db.list_consultants()
        if not consultants:
            return {"reply": "There are no consultants in this workspace "
                             "yet — add one from the Consultants tab first.",
                    "ai": False, "action": None}
        c = _find_consultant(text, consultants)
        if not c:
            names = ", ".join(x["name"] for x in consultants)
            return {"reply": f"Whose resume should I tailor? This "
                             f"workspace has: {names}. Say, for example, "
                             f"\"tailor {consultants[0]['name']}'s resume\".",
                    "ai": False, "action": None}
        matches = db.list_matches(c["id"])
        if not matches:
            return {"reply": f"{c['name']} has no matches yet — run a "
                             f"job collection first, then ask me again.",
                    "ai": False, "action": None}
        low = text.lower()
        pick = next((m for m in matches
                     if (m.get("company") or "").lower() in low
                     or (m.get("job_title") or "").lower() in low), matches[0])
        out = _run_tailor(pick)
        _last_action[key] = {
            "match_id": pick["id"], "tailored_id": out["id"],
            "consultant_name": c["name"], "job_title": pick["job_title"],
            "company": pick["company"]}
        made = ("the AI" if out["tailored_by"] == "llm"
                else "the built-in editor (no AI key working in this "
                     "workspace, so it ran in standard mode)")
        reply = (f"Done — tailored {c['name']}'s resume for "
                 f"{pick['job_title']} at {pick['company']} "
                 f"(match score {pick['score']}), written by {made}.")
        flagged = out["added_skills_flagged"] or []
        if flagged:
            reply += (f"\n\n⚠ Flagged — these were NOT added, because "
                      f"they are not in the original resume: "
                      f"{', '.join(flagged)}. If {c['name']} truly has "
                      f"them, confirm in the match's Tailor screen.")
        reply += ('\n\nSay "queue it" to add this to the Apply Queue '
                  "with the tailored resume attached.")
        return {"reply": reply, "ai": False,
                "action": {"type": "tailored", "match_id": pick["id"],
                           "tailored_id": out["id"]}}
    return None


def chat(message: str, history: list | None = None,
         actor: str = "") -> dict:
    """Answer one message, or run a tailor/queue action when asked.
    Returns {"reply": str, "ai": bool, "action": dict | None}."""
    message = (message or "").strip()[:2000]
    if not message:
        return {"reply": "Ask me about your consultants, top matches, "
                         "the apply queue, or how anything in BenchPilot "
                         "works.", "ai": False, "action": None}
    acted = _try_action(message, actor)
    if acted is not None:
        return acted
    settings = db.get_settings()
    if not (settings.get("llm_base_url") and settings.get("llm_api_key")
            and settings.get("llm_model")):
        return {"reply": _NO_AI, "ai": False, "action": None}
    messages = [{"role": "system",
                 "content": SYSTEM + "\n" + APP_GUIDE + "\n" + build_snapshot()}]
    for h in (history or [])[-8:]:
        if isinstance(h, dict) and h.get("content"):
            role = "assistant" if h.get("role") == "assistant" else "user"
            messages.append({"role": role,
                             "content": str(h["content"])[:2000]})
    messages.append({"role": "user", "content": message})
    reply = _call_llm(settings, messages)
    if reply is None:
        return {"reply": "The AI didn't answer just now — the workspace's "
                         "AI settings may be unreachable. Try again in a "
                         "moment; if it keeps failing, an admin can check "
                         "the AI settings in Settings.", "ai": False,
                "action": None}
    return {"reply": reply, "ai": True, "action": None}
