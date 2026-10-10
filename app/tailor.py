"""Resume tailoring for BenchPilot.

Two paths:
- LLM (OpenAI-compatible /chat/completions) when llm_* settings are present.
- Keyword fallback when no LLM is configured (works with zero keys).

HARD RULE shared by both: never add skills, tools, employers, or dates that
are not present in the original resume.
"""
import re
import requests

from .skills import extract_skills

LLM_SYSTEM = """You rewrite a candidate's resume to better match a job description.

HARD RULES (never break these):
- NEVER add skills, tools, technologies, employers, job titles, or dates that
  are not present in the original resume.
- NEVER change factual claims: employers, dates, degrees, locations stay identical.
- Only: rewrite the professional summary using resume facts + the JD's keywords;
  reorder/rephrase bullet points so bullets demonstrating the JD's most-wanted
  skills come first; reorder the skills list by JD relevance.
- Output ONLY the rewritten resume as plain text, no commentary."""


def _llm_tailor(raw_text: str, jd_text: str, settings: dict) -> str | None:
    base = (settings.get("llm_base_url") or "").rstrip("/")
    key = settings.get("llm_api_key") or ""
    model = settings.get("llm_model") or ""
    if not (base and key and model):
        return None
    user = (f"ORIGINAL RESUME:\n{raw_text}\n\nJOB DESCRIPTION:\n{jd_text}\n\n"
            "Rewrite the resume per the rules. Plain text only.")
    try:
        resp = requests.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "system", "content": LLM_SYSTEM},
                               {"role": "user", "content": user}],
                  "temperature": 0.3, "max_tokens": 4000},
            timeout=90,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None  # caller falls back to keyword tailor


def _is_bullet(line: str) -> bool:
    s = line.lstrip()
    return bool(re.match(r"^([-\u2022*]|\d+[.)])\s+\S", s))


def _skill_hit(line: str, skills: set[str]) -> bool:
    low = line.lower()
    return any(s in low for s in skills)


def keyword_tailor(raw_text: str, resume_skills: list[str], jd_text: str) -> str:
    """Reorder skills section by JD relevance, enrich summary with matched
    keywords, bubble matched bullets to the top of each bullet run."""
    rset = set(resume_skills)
    jd_skills = set(extract_skills(jd_text))
    matched = sorted(rset & jd_skills)
    unmatched = sorted(rset - jd_skills)
    ordered = matched + unmatched

    lines = raw_text.splitlines()

    # 1) skills section
    skills_line = "Skills: " + ", ".join(ordered)
    sec_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*(technical\s+skills|core\s+skills|skills|technologies|"
                    r"tech\s+stack)\b\s*:?\s*$", line, re.I):
            sec_idx = i
            break
    if sec_idx is not None:
        j = sec_idx + 1
        while j < len(lines) and lines[j].strip() and not re.match(
                r"^\s*[A-Z][A-Za-z /&]{2,40}:?\s*$", lines[j]):
            j += 1
        section = lines[sec_idx + 1:j]
        label_re = re.compile(r"^(\s*[^:,]{2,40}:\s*)(\S.*)$")
        labelled = [ln for ln in section if label_re.match(ln)]
        non_empty = [ln for ln in section if ln.strip()]
        if labelled and len(labelled) * 2 >= len(non_empty):
            # categorised skills ("Languages: Java, Python"): keep the
            # candidate's own lines and categories, only move the skills this
            # job asks for to the front of each line.
            mset0 = set(matched)
            new_section = []
            for ln in section:
                m = label_re.match(ln)
                if m:
                    items = [x.strip() for x in m.group(2).split(",") if x.strip()]
                    items.sort(key=lambda it: not _skill_hit(it, mset0))  # stable
                    ln = m.group(1) + ", ".join(items)
                new_section.append(ln)
            lines[sec_idx + 1:j] = new_section
        else:
            lines[sec_idx:j] = [lines[sec_idx].rstrip() or "Skills", skills_line]
    else:
        insert_at = 1 if lines else 0
        lines.insert(insert_at, skills_line)

    # 2) summary enrichment
    if matched:
        add = ("Key strengths for this role include: " +
               ", ".join(matched[:6]) + ".")
        sum_idx = None
        for i, line in enumerate(lines):
            if re.match(r"^\s*(professional\s+)?summary|profile|objective\b",
                        line, re.I):
                sum_idx = i
                break
        if sum_idx is not None:
            k = sum_idx + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            while k < len(lines) and lines[k].strip():
                k += 1
            lines.insert(k, add)
        else:
            lines.insert(min(2, len(lines)), add)

    # 3) reorder bullets within each contiguous bullet run
    out: list[str] = []
    i = 0
    mset = set(matched)
    while i < len(lines):
        if _is_bullet(lines[i]):
            j = i
            while j < len(lines) and _is_bullet(lines[j]):
                j += 1
            run = lines[i:j]
            run.sort(key=lambda ln: (not _skill_hit(ln, mset)))
            out.extend(run)
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def add_skills_to_text(text: str, skills: list[str]) -> str:
    """Insert user-confirmed skills into the resume's skills section.

    Only call with skills the recruiter explicitly confirmed the candidate
    has (this is the honesty gate - the function itself does no validation).
    Categorised lines ("Languages: Java, Python") get the new skills appended
    to the last labelled line; a plain skills block gets an
    "Additional skills:" line. Skills already present are skipped.
    """
    clean = []
    for s in skills or []:
        s = (s or "").strip()
        if s and s.lower() not in {c.lower() for c in clean}:
            clean.append(s)
    if not clean or not text:
        return text

    label_re = re.compile(r"^(\s*[^:,]{2,40}:\s*)(\S.*)$")
    lines = text.splitlines()
    sec_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*(technical\s+skills|core\s+skills|skills|technologies|"
                    r"tech\s+stack)\b\s*:?\s*$", line, re.I):
            sec_idx = i
            break
    if sec_idx is None:
        lines.insert(1 if lines else 0, "Skills: " + ", ".join(clean))
        return "\n".join(lines)

    j = sec_idx + 1
    while j < len(lines) and lines[j].strip() and not re.match(
            r"^\s*[A-Z][A-Za-z /&]{2,40}:?\s*$", lines[j]):
        j += 1
    section = lines[sec_idx + 1:j]
    present = set()
    for ln in section:
        m = label_re.match(ln)
        if m:
            present.update(x.strip().lower() for x in m.group(2).split(",") if x.strip())
    new = [s for s in clean if s.lower() not in present]
    if not new:
        return text
    labelled = [ln for ln in section if label_re.match(ln)]
    if labelled:
        idx = section.index(labelled[-1])
        m = label_re.match(section[idx])
        items = [x.strip() for x in m.group(2).split(",") if x.strip()]
        items.extend(new)
        section[idx] = m.group(1) + ", ".join(items)
        lines[sec_idx + 1:j] = section
    else:
        lines.insert(j, "Additional skills: " + ", ".join(new))
    return "\n".join(lines)


def tailor_match(match: dict, settings: dict) -> dict:
    """Tailor the resume for a match dict (from db.get_match).
    Returns {text, tailored_by, added_skills_flagged}."""
    raw = match.get("resume_text") or ""
    rskills = list(match.get("resume_skills") or [])
    jd = match.get("job_description") or ""

    text = _llm_tailor(raw, jd, settings)
    tailored_by = "llm" if text else "keyword-fallback"
    if not text:
        text = keyword_tailor(raw, rskills, jd)

    # post-check: flag any skill in tailored text not in the original resume
    flagged = sorted(set(extract_skills(text)) - set(rskills))
    return {"text": text, "tailored_by": tailored_by,
            "added_skills_flagged": flagged}
