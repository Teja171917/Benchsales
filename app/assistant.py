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
import requests

from . import db

SYSTEM = """You are the BenchPilot assistant, helping a bench sales /
recruiting team inside their own BenchPilot workspace.

Rules:
- Answer ONLY from the WORKSPACE DATA and APP GUIDE below. If the answer
  is not there, say you don't see it in this workspace and name the tab
  where the person can check (Overview, Consultants, Jobs, Matches,
  Apply Queue, Agent Office, Settings).
- Never invent numbers, names, companies, salaries, or jobs.
- You are read-only: you cannot queue, apply, send email, or change
  anything. When someone asks you to do something, give the exact steps
  to do it in the app instead.
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


def chat(message: str, history: list | None = None) -> dict:
    """Answer one message. Returns {"reply": str, "ai": bool}."""
    message = (message or "").strip()[:2000]
    if not message:
        return {"reply": "Ask me about your consultants, top matches, "
                         "the apply queue, or how anything in BenchPilot "
                         "works.", "ai": False}
    settings = db.get_settings()
    if not (settings.get("llm_base_url") and settings.get("llm_api_key")
            and settings.get("llm_model")):
        return {"reply": _NO_AI, "ai": False}
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
                         "the AI settings in Settings.", "ai": False}
    return {"reply": reply, "ai": True}
