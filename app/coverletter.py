"""Cover letters for applications that expect one — mainly full-time
roles, where a bare resume (the contract-world norm) is thin.

Two modes, mirroring resume tailoring: the workspace's AI model writes
the letter when one is configured, otherwise a clean template is built
from the consultant, the job, and the skills both sides share. Either
way the letter uses ONLY facts from the resume and the posting — no
invented employers, years, or achievements.
"""
import requests

from . import skills as skills_mod

LLM_SYSTEM = """You write a short, professional cover letter for a job
application, in the candidate's first-person voice.

Rules:
- Use ONLY facts present in the resume text and the job details given.
  Never invent employers, dates, years of experience, projects, or
  achievements.
- 3 short paragraphs plus a sign-off: (1) the role and company applied
  for and the candidate's fit in one line, (2) the strongest matching
  skills/experience from the resume for this job, (3) interest in the
  role and a polite close.
- Plain text only. Start with the candidate's name and contact line,
  then "Dear Hiring Manager,". Sign off with the candidate's name.
- Keep it under 220 words. No placeholders like [Company]."""


def matched_skills(resume_text: str, jd_text: str, limit: int = 8) -> list:
    """Skills the posting asks for that the resume actually has."""
    have = set(skills_mod.extract_skills(resume_text or ""))
    want = set(skills_mod.extract_skills(jd_text or ""))
    both = sorted(have & want)
    return [skills_mod.display_name(s) for s in both[:limit]]


def template_letter(consultant: dict, job: dict, matched: list) -> str:
    name = consultant.get("name") or "Candidate"
    contact = " · ".join(x for x in (consultant.get("location") or "",
                                     consultant.get("email") or "",
                                     consultant.get("phone") or "") if x)
    title = job.get("title") or "the open role"
    company = job.get("company") or "your company"
    lines = [name]
    if contact:
        lines.append(contact)
    lines += ["", "Dear Hiring Manager,",
              "",
              f"I am writing to apply for the {title} position at "
              f"{company}. Based on the role's requirements, I believe "
              f"my background is a strong match, and I would welcome the "
              f"opportunity to bring that experience to your team."]
    if matched:
        lines += ["",
                  "My experience includes " + ", ".join(matched) +
                  " — the same strengths this position calls for. I have "
                  "applied these skills to deliver reliable, production-"
                  "quality work, and I am confident I can contribute "
                  "quickly in this role."]
    lines += ["",
              "I would appreciate the chance to discuss how my "
              "background fits what you are building. Thank you for "
              "your time and consideration.",
              "",
              "Sincerely,",
              name]
    return "\n".join(lines)


def _llm_letter(consultant: dict, job: dict, resume_text: str,
                settings: dict) -> str | None:
    base = (settings.get("llm_base_url") or "").rstrip("/")
    key = settings.get("llm_api_key") or ""
    model = settings.get("llm_model") or ""
    if not (base and key and model):
        return None
    user = (f"JOB: {job.get('title') or ''} at {job.get('company') or ''}\n"
            f"JOB DESCRIPTION:\n{(job.get('description') or '')[:3000]}\n\n"
            f"CANDIDATE: {consultant.get('name') or ''} | "
            f"{consultant.get('location') or ''} | "
            f"{consultant.get('email') or ''} | "
            f"{consultant.get('phone') or ''}\n"
            f"RESUME:\n{(resume_text or '')[:6000]}")
    try:
        r = requests.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "temperature": 0.3, "max_tokens": 800,
                  "messages": [{"role": "system", "content": LLM_SYSTEM},
                               {"role": "user", "content": user}]},
            timeout=60)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception:
        return None


def generate(consultant: dict, job: dict, resume_text: str,
             settings: dict) -> tuple:
    """Returns (letter_text, made_by) with made_by 'llm' or 'template'."""
    text = _llm_letter(consultant, job, resume_text, settings)
    if text:
        return text, "llm"
    matched = matched_skills(resume_text, job.get("description") or "")
    return template_letter(consultant, job, matched), "template"
