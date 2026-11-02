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
from .skills import display_name, extract_skills

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
- The RECENT ACTIVITY section is this workspace's own log of actions
  and errors. For questions about what happened, what failed, or who
  did something, answer from it and quote its times and details.
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
  with the tailored resume attached.
- "Add the missing skills for this post" lists the skills a match asks
  for that the resume doesn't show. They are added ONLY when the person
  confirms them here ("confirm Kubernetes" / "confirm all") — that
  confirmation is the attestation that the consultant truly has them,
  recorded against the tailored resume. Nothing is ever added silently.
- "Approve <skill> for <name>" records a STANDING approval: the team
  attests once that the consultant has that skill, and from then on
  it is added to tailored resumes automatically whenever a post
  asks for it — always noted as coming from the standing approval.
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
        line = (
            f"- {c['name']}"
            + (f" ({c['location']})" if c.get("location") else "")
            + f": {n} matches"
            + (f", best score {best}" if best is not None else "")
            + ("" if c.get("has_resume") else ", NO RESUME uploaded"))
        gaps = db.skill_gaps(c["id"], limit=5)["gaps"]
        if gaps:
            line += ("; top skill gaps (asked for by their matches, not "
                     "on the resume): "
                     + ", ".join(g["skill"] for g in gaps))
        lines.append(line)
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
    events = db.list_activity(limit=12)
    if events:
        lines.append("RECENT ACTIVITY IN THIS WORKSPACE (newest first — "
                     "actions and errors recorded as they happened; use "
                     "it for 'what happened', error and who-did-what "
                     "questions):")
        for e in events:
            line = (f"- [{(e.get('created_at') or '')[:16].replace('T', ' ')}] "
                    f"[{e.get('kind', 'action')}] {e.get('summary', '')}")
            if e.get("actor"):
                line += f" (by {e['actor']})"
            if e.get("detail"):
                line += f" — {e['detail']}"
            lines.append(line)
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
    try:
        result = tailor_mod.tailor_match(match, db.get_settings())
    except Exception as exc:
        db.log_activity(
            "error",
            f"Tailor failed for {match.get('consultant_name', 'a consultant')}"
            f" — {match.get('job_title', '')} at {match.get('company', '')}",
            actor="assistant", detail=f"{type(exc).__name__}: {exc}")
        raise
    tid = db.insert_tailored(match["id"], result["text"],
                             result["tailored_by"],
                             result["added_skills_flagged"])
    db.log_activity(
        "action",
        f"Tailored {match.get('consultant_name', 'a consultant')}'s resume"
        f" for {match.get('job_title', '')} at {match.get('company', '')}"
        f" ({result['tailored_by']})",
        actor="assistant")
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


def _add_confirmed_skills(tailored: dict, match: dict,
                          skills: list) -> list:
    """The Tailor screen's honesty gate, run from chat: only skills
    listed as missing for this match may be added, and only the ones
    the person just confirmed. Returns the skills actually added."""
    allowed = set(match.get("missing_skills") or [])
    allowed |= set(tailored.get("user_confirmed_skills") or [])
    clean = []
    for s in skills:
        if s in allowed and s not in clean:
            clean.append(s)
    if not clean:
        return []
    new_text = tailor_mod.add_skills_to_text(
        tailored["tailored_text"], [display_name(s) for s in clean])
    db.update_tailored(tailored["id"], new_text, clean)
    return clean


def _approved_skills(cid: int) -> set:
    c = db.get_consultant(cid) or {}
    rules = c.get("rules") or {}
    return {str(x).lower() for x in (rules.get("approved_skills") or [])}


def _auto_add_approved(cid: int, match: dict, tailored: dict) -> list:
    """Add any of this match's missing/flagged skills that carry a
    standing approval (a team member attested earlier, on record, that
    the consultant has them). Returns what was added."""
    approved = _approved_skills(cid)
    if not approved:
        return []
    already = set(tailored.get("user_confirmed_skills") or [])
    candidates = []
    for s in (match.get("missing_skills") or []) \
            + (tailored.get("added_skills_flagged") or []):
        if s not in already and s not in candidates:
            candidates.append(s)
    auto = [c for c in candidates if c.lower() in approved]
    if not auto:
        return []
    return _add_confirmed_skills(tailored, match, auto)


def _try_action(message: str, actor: str) -> dict | None:
    """Run a tailor/queue action when the message asks for one.
    Returns a chat reply dict, or None to fall through to the model."""
    key = (str(db.current_path()), actor or "shared")
    text = message.strip()
    low = text.lower()
    state = _last_action.get(key)

    # --- standing approval: "approve <skill> for <name>" ---------------
    if re.match(r"^(approve|authorize|authorise)\b", low):
        consultants = db.list_consultants()
        c = _find_consultant(text, consultants)
        if not c:
            names = ", ".join(x["name"] for x in consultants)
            return {"reply": "Approve a skill for whom? This workspace "
                             f"has: {names}. Say, for example, "
                             "\"approve Kubernetes for "
                             f"{consultants[0]['name'] if consultants else 'a consultant'}\".",
                    "ai": False, "action": None}
        rest = re.sub(r"^(approve|authorize|authorise)\b", "", low).strip()
        phrase = re.split(r"\bfor\b", rest, maxsplit=1)[0].strip()
        for tok in re.split(r"[^a-z0-9]+", c["name"].lower()):
            if len(tok) >= 3:
                phrase = phrase.replace(tok, " ").strip()
        canon = extract_skills(phrase) or ([phrase] if phrase else [])
        if not canon:
            return {"reply": "Which skill should I approve? Say, for "
                             f"example, \"approve Kubernetes for "
                             f"{c['name']}\".",
                    "ai": False, "action": None}
        full_c = db.get_consultant(c["id"]) or {}
        rules = dict(full_c.get("rules") or {})
        approved = sorted(set(rules.get("approved_skills") or [])
                          | {str(x).lower() for x in canon})
        rules["approved_skills"] = approved
        db.update_consultant(c["id"], {"rules": rules})
        return {"reply":
                f"Standing approval recorded for {c['name']}: "
                + ", ".join(display_name(x) for x in canon)
                + ". From now on, when a post asks for "
                + ("it" if len(canon) == 1 else "them")
                + " and the resume doesn't show it, I will add it to "
                  "the tailored resume automatically and note it came "
                  "from this approval. Every other missing skill still "
                  "needs a per-post confirm.",
                "ai": False,
                "action": {"type": "skill_approved",
                           "consultant_id": c["id"], "skills": canon}}

    # --- step 2 of the skills flow: an explicit confirmation ----------
    if state and state.get("kind") == "awaiting_skill_confirm":
        candidates = state["candidates"]
        if low.startswith("confirm") or "add them" in low \
                or "add all" in low:
            if "all" in low:
                chosen = list(candidates)
            else:
                chosen = [c for c in candidates
                          if c.lower() in low
                          or display_name(c).lower() in low]
            if not chosen:
                return {"reply":
                        "Which of these should I add? "
                        + ", ".join(display_name(c) for c in candidates)
                        + '. Reply e.g. "confirm '
                        + display_name(candidates[0]) + '" or "confirm all".',
                        "ai": False, "action": None}
            t = db.get_tailored(state["tailored_id"])
            m = db.get_match(state["match_id"])
            added = _add_confirmed_skills(t, m, chosen)
            state["kind"] = "tailored"
            state.pop("candidates", None)
            remaining = [c for c in candidates if c not in added]
            reply = ("Added to the tailored resume: "
                     + ", ".join(display_name(a) for a in added)
                     + f" — recorded as confirmed by you for "
                       f"{state['consultant_name']}.")
            if remaining:
                reply += ("\n\nNot added: "
                          + ", ".join(display_name(r) for r in remaining)
                          + ".")
            reply += ('\n\nSay "queue it" to queue the updated resume '
                      "for this job.")
            return {"reply": reply, "ai": False,
                    "action": {"type": "skills_confirmed",
                               "match_id": state["match_id"],
                               "added": added}}
        if any(w in low for w in ("skip", "none", "don't", "do not",
                                  "no thanks")):
            state["kind"] = "tailored"
            state.pop("candidates", None)
            return {"reply":
                    "OK — nothing was added. The tailored resume stays "
                    "exactly as the consultant's real resume supports."
                    '\n\nSay "queue it" to queue it as-is.',
                    "ai": False, "action": None}

    # --- step 1 of the skills flow: offer the missing skills ----------
    if "skill" in low and any(w in low for w in
                              ("add", "update", "miss", "fix", "include",
                               "cover")):
        consultants = db.list_consultants()
        c = _find_consultant(text, consultants)
        match = None
        if c:
            matches = db.list_matches(c["id"])
            if matches:
                match = next((m for m in matches
                              if (m.get("company") or "").lower() in low
                              or (m.get("job_title") or "").lower()
                              in low), matches[0])
        elif state and state.get("match_id"):
            match = db.get_match(state["match_id"])
            c = next((x for x in consultants
                      if x["name"] == state.get("consultant_name")), None)
        if not c or not match:
            names = ", ".join(x["name"] for x in consultants)
            return {"reply":
                    "Whose missing skills — and for which post? This "
                    f"workspace has: {names}. Say, for example, "
                    f"\"add the missing skills for "
                    f"{consultants[0]['name'] if consultants else 'a consultant'}\".",
                    "ai": False, "action": None}
        full = db.get_match(match["id"])
        row = db.get_tailored_for_match(match["id"])
        if not row:
            out = _run_tailor(full)
            row = {"id": out["id"]}
        tailored = db.get_tailored(row["id"])
        auto = _auto_add_approved(c["id"], full, tailored)
        if auto:
            tailored = db.get_tailored(tailored["id"])
        already = set(tailored.get("user_confirmed_skills") or [])
        candidates = []
        for s in (full.get("missing_skills") or []) \
                + (tailored.get("added_skills_flagged") or []):
            if s not in already and s not in candidates:
                candidates.append(s)
        auto_note = (""
                     if not auto else
                     "Added per standing approval: "
                     + ", ".join(display_name(a) for a in auto) + ".\n\n")
        if not candidates:
            _last_action[key] = {
                "kind": "tailored", "match_id": match["id"],
                "tailored_id": tailored["id"],
                "consultant_name": c["name"],
                "job_title": full["job_title"], "company": full["company"]}
            return {"reply":
                    auto_note
                    + (f"Nothing else is missing — {c['name']}'s resume "
                       f"now covers every skill the {full['job_title']} "
                       f"post at {full['company']} asks for."
                       if auto else
                       f"Nothing is missing — {c['name']}'s resume "
                       f"already covers every skill the "
                       f"{full['job_title']} post at {full['company']} "
                       f"asks for.")
                    + '\n\nSay "queue it" to queue the tailored resume.',
                    "ai": False, "action": None}
        _last_action[key] = {
            "kind": "awaiting_skill_confirm", "match_id": match["id"],
            "tailored_id": tailored["id"], "candidates": candidates,
            "consultant_name": c["name"], "job_title": full["job_title"],
            "company": full["company"]}
        return {"reply":
                auto_note
                + f"For {full['job_title']} at {full['company']}, "
                f"{c['name']}'s resume is missing: "
                + ", ".join(display_name(s) for s in candidates)
                + ".\n\nI won't add these on my own — that would be "
                  "inventing experience. If "
                + c["name"]
                + " truly has them, reply \"confirm "
                + display_name(candidates[0])
                + "\" (name each one) or \"confirm all\", and I will add "
                  "exactly those to the tailored resume, recorded as "
                  "confirmed by you.",
                "ai": False,
                "action": {"type": "skills_offered",
                           "match_id": match["id"],
                           "candidates": candidates}}
    # queue follow-up ("queue it") after a tailor action
    if _QUEUE_WORDS.search(text) and key in _last_action:
        last = _last_action.pop(key)
        db.queue_application(last["match_id"], last["tailored_id"])
        _qm = db.get_match(last["match_id"]) or {}
        db.log_activity(
            "action",
            f"Queued {_qm.get('consultant_name', 'a consultant')} for "
            f"{_qm.get('job_title', '')} at {_qm.get('company', '')}",
            actor="assistant")
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
            "kind": "tailored",
            "match_id": pick["id"], "tailored_id": out["id"],
            "consultant_name": c["name"], "job_title": pick["job_title"],
            "company": pick["company"]}
        made = ("the AI" if out["tailored_by"] == "llm"
                else "the built-in editor (no AI key working in this "
                     "workspace, so it ran in standard mode)")
        reply = (f"Done — tailored {c['name']}'s resume for "
                 f"{pick['job_title']} at {pick['company']} "
                 f"(match score {pick['score']}), written by {made}.")
        auto = _auto_add_approved(c["id"], db.get_match(pick["id"]),
                                  db.get_tailored(out["id"]))
        if auto:
            reply += ("\n\nAdded per standing approval: "
                      + ", ".join(display_name(a) for a in auto) + ".")
        flagged = [f for f in (out["added_skills_flagged"] or [])
                   if f not in auto]
        if flagged:
            reply += (f"\n\n⚠ Flagged — these were NOT added, because "
                      f"they are not in the original resume: "
                      f"{', '.join(flagged)}. If {c['name']} truly has "
                      f"them, confirm in the match's Tailor screen.")
        missing = pick.get("missing_skills") or []
        if missing:
            reply += ("\n\nMissing for this post: "
                      + ", ".join(display_name(s) for s in missing[:8])
                      + '. Say "add the missing skills" to review them '
                        "for confirmation.")
        reply += ('\n\nSay "queue it" to add this to the Apply Queue '
                  "with the tailored resume attached.")
        return {"reply": reply, "ai": False,
                "action": {"type": "tailored", "match_id": pick["id"],
                           "tailored_id": out["id"]}}
    return None


_ACTIVITY_WORDS = re.compile(
    r"\b(errors?|failed|failing|failure|activity|what happened|"
    r"recent events|history)\b", re.I)


def _activity_reply(message: str) -> str:
    """Answer 'what happened / any errors?' straight from this
    workspace's activity log — no model needed, so it works even when
    the workspace's AI is off or unreachable."""
    wants_errors = bool(re.search(r"\berrors?\b|\bfailed\b|\bfailure\b",
                                  message, re.I))
    errors = db.list_activity(limit=8, kind="error")
    events = db.list_activity(limit=10)
    if not events and not errors:
        return ("Nothing is in this workspace's activity log yet. "
                "Tailoring, queueing, collections and errors will show "
                "up here as they happen.")
    lines = []
    if wants_errors:
        if errors:
            lines.append("Recent errors in this workspace:")
            for e in errors:
                lines.append(
                    f"- [{(e.get('created_at') or '')[:16].replace('T', ' ')}] "
                    f"{e.get('summary', '')}"
                    + (f" — {e['detail']}" if e.get("detail") else ""))
        else:
            lines.append("No errors in the recent activity log.")
        lines.append("")
        lines.append("Latest activity:")
    else:
        lines.append("Recent activity in this workspace (newest first):")
    for e in events:
        lines.append(
            f"- [{(e.get('created_at') or '')[:16].replace('T', ' ')}] "
            f"{e.get('summary', '')}"
            + (f" (by {e['actor']})" if e.get("actor") else ""))
    return "\n".join(lines)


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
    if _ACTIVITY_WORDS.search(message):
        return {"reply": _activity_reply(message), "ai": False,
                "action": None}
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
