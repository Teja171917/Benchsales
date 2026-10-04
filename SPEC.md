# BenchPilot — SPEC v1

Recruiter + bench-sales automation web app. A staffing team keeps resumes for
~10 bench consultants in the app; the app pulls jobs from the big boards,
scores every consultant against every job, tailors the resume to the job
description (without inventing experience), and manages an apply queue with a
placement pipeline.

## Non-goals for v1 (be honest in docs/UI)
- "All jobs online" = broad aggregation, not literal completeness. LinkedIn and
  Indeed block scraping; they are covered via the JSearch aggregator API
  (Google for Jobs -> LinkedIn/Indeed/Glassdoor/ZipRecruiter) and via manual
  URL import by recruiters.
- "Auto-apply" v1 = assisted apply: one-click apply links + status tracking.
  True hands-off auto-apply needs per-site recruiter logins and breaks on
  bot checks; it is roadmap, not v1.

## Stack
- Python 3.11+, FastAPI, SQLite (stdlib sqlite3, no ORM), vanilla JS + CSS
  frontend served as static files. No build step.
- PDF: pypdf. DOCX: python-docx. Web extraction: trafilatura (fallback:
  readability regex strip).
- Deps pinned in requirements.txt; `./start.sh` creates venv, installs,
  runs `uvicorn app.server:app --host 127.0.0.1 --port 8741`.

## Data model (SQLite, `data/benchpilot.db`)
- consultants(id, name, email, phone, location, visa_status, linkedin_url,
  notes, created_at)
- resumes(id, consultant_id, filename, raw_text, skills_json, uploaded_at)
  (one active resume per consultant for v1; re-upload replaces)
- jobs(id, source, source_id, title, company, location, remote_flag,
  url, description, posted_at, salary, employment_type, fetched_at,
  UNIQUE(source, source_id))
- matches(id, consultant_id, job_id, score, score_breakdown_json,
  missing_skills_json, created_at, UNIQUE(consultant_id, job_id))
- tailored_resumes(id, match_id, tailored_text, added_skills_flagged_json,
  created_at)
- applications(id, match_id, status, tailored_resume_id, applied_at,
  notes, updated_at)  status in queued|applied|screening|interview|
  offered|placed|rejected|withdrawn
- settings(key, value) — adzuna_app_id, adzuna_app_key, rapidapi_key
  (JSearch), llm_base_url, llm_api_key, llm_model, match_threshold (default 60),
  search_queries (JSON list of {title, location}), enabled_sources (JSON)
- api keys are stored server-side only, never returned by the API.

## Job sources (pluggable adapters in app/sources/, each with `fetch(query)`
# -> list[dict], and `enabled()` check; a source with missing creds is
# skipped silently with a status line in the collector log)
1. adzuna.py — https://api.adzuna.com/v1/api/jobs/us/search/{page}
   ?app_id=&app_key=&what=&where=&results_per_page=50 . Free key from
   developer.adzuna.com. Broad aggregator.
2. jsearch.py — RapidAPI JSearch. NOTE: as of 2026 the working endpoint is
   `/search-v2` (old `/search` 404s). Verify at build time. Headers:
   X-RapidAPI-Key, X-RapidAPI-Host: jsearch.p.rapidapi.com.
   Aggregates LinkedIn/Indeed/Glassdoor/ZipRecruiter. Full JD text.
3. remoteok.py — https://remoteok.com/api (no key). Remote tech jobs.
4. remotive.py — https://remotive.com/api/remote-jobs (no key).
5. urlimport.py — NOT a scheduled source. API endpoint accepts any job posting
   URL, fetches it, extracts title/company/description. This is how recruiters
   add LinkedIn/Indeed/Dice postings they find manually.
6. dice.py — PROBE at build time: try https://www.dice.com/api/jobs/search?q=
   and /api/jobs?q= variants. If a JSON endpoint answers, implement it;
   otherwise SKIP the adapter cleanly (Dice coverage comes via Adzuna + URL
   import). Do not ship a broken Dice adapter.
- collector.py: for each enabled source x each search query -> fetch ->
  normalize -> dedupe on (source, source_id) and fuzzy (title+company+location)
  -> insert new jobs -> run matcher for all consultants. Prints a summary.
  Safe to re-run (idempotent).

## Skill extraction & matching
- app/skills.py: curated lexicon (~300-500 entries: languages, frameworks,
  clouds, tools, methodologies, e.g. "java", "spring boot", "aws", "selenium",
  "ci/cd"). Phrase matching, case-insensitive, with simple normalizations
  (e.g. "k8s"->"kubernetes"). Extract from resume text and job description.
- app/matcher.py score 0-100:
  - 70% skill overlap: |resume_skills ∩ jd_skills| / |jd_skills|, weighted:
    skills appearing in the JD's "requirements" section count 2x (naive
    section detection: lines under a "requirements|qualifications" heading).
  - 20% title similarity: token overlap between consultant's latest title
    (first line of resume or parsed) and job title.
  - 10% location/remote fit: remote job = full marks; else token overlap of
    locations.
  - Recency boost: +5 if posted within 7 days (cap at 100).
  - Only create a match row when score >= match_threshold setting.
- Return score_breakdown {skill, title, location, recency} and missing_skills
  (jd skills not in resume) for the UI.

## Resume tailoring (app/tailor.py)
- Input: resume raw_text + skills, job description + extracted jd skills.
- If llm configured: call OpenAI-compatible /chat/completions with a strict
  prompt: rewrite professional summary + reorder/rephrase bullets to mirror
  the JD's keywords; HARD RULES: never add skills, tools, employers, or
  dates not present in the original resume; keep all factual claims identical;
  output plain text resume. Temperature 0.3.
- Post-check: extract skills from tailored text; any skill not in the original
  resume's skill set -> added_skills_flagged list. If non-empty, the UI shows
  a warning banner and the recruiter must acknowledge before queueing.
- If no llm configured: keyword fallback tailor — regenerate the skills
  section ordered by JD relevance (only skills the resume actually has),
  rewrite the summary from resume facts + top JD keywords, reorder bullets so
  bullets containing matched skills come first. Mark output `tailored_by:
  "keyword-fallback"`.
- Store tailored text; UI shows side-by-side original vs tailored with a
  diff-ish highlight of changed lines (simple line-diff is fine).

## API (FastAPI, JSON)
- GET /api/consultants, POST /api/consultants, PUT /api/consultants/{id},
  DELETE /api/consultants/{id}
- POST /api/consultants/{id}/resume (multipart file .pdf/.docx/.txt)
  -> parses, extracts skills, returns them
- GET /api/consultants/{id} (includes resume skills)
- GET /api/jobs?source=&q=&limit= (newest first)
- POST /api/jobs/import-url {url} (urlimport adapter)
- POST /api/collect (runs collector synchronously, returns summary;
  warn it can take 1-3 min)
- GET /api/matches?consultant_id=&min_score= (job embedded)
- GET /api/matches/{id} (breakdown + missing skills)
- POST /api/matches/{id}/tailor -> tailored_resumes row
- GET /api/tailored/{id}
- POST /api/matches/{id}/queue -> applications row (status=queued)
- GET /api/applications?status= ; PATCH /api/applications/{id} {status, notes}
- GET /api/settings (keys masked), PUT /api/settings
- GET /api/sources/status (each source: enabled/configured/last run count)

## Frontend (frontend/index.html + app.js + styles.css)
Single-page dashboard, clean and fast. Tabs:
1. Consultants — cards for the 10 consultants; add/edit; upload resume;
   shows parsed skill chips.
2. Jobs — table/cards: title, company, location, source badge, posted date,
   "Import URL" box at top, "Run job collection" button with progress.
3. Matches — filter by consultant; each match: score bar, breakdown tooltip,
   missing-skills chips, buttons: "Tailor resume", "Queue for apply".
4. Tailor view — modal or pane: side-by-side original/tailored, flagged-skills
   warning if any, "Save & queue" button.
5. Apply Queue — kanban-ish columns by status (Queued, Applied, Screening,
   Interview, Offered, Placed, Rejected); each card: consultant, job, company,
   apply link (opens posting), tailored resume download, status mover, notes.
6. Settings — API keys (Adzuna, RapidAPI/JSearch, LLM base URL/key/model),
   search queries editor (title + location rows), enabled sources toggles,
   match threshold slider. Keys displayed masked.
Design: professional staffing-tool look, no purple gradients, no emojis in UI.

## Security/privacy notes
- Runs on localhost by default; bind 0.0.0.0 only if the team hosts it
  themselves (documented in RUNBOOK).
- Optional shared password gate via env BENCHPILOT_PASSWORD (HTTP basic auth
  on all routes when set).
- Never log API keys or resume full text to console; mask keys in API.

## Deliverables in ~/workspace/benchpilot/
- app/, frontend/, collector.py, requirements.txt, start.sh, SPEC.md (this),
  RUNBOOK.md (setup, keys signup links, daily workflow, hosting options,
  roadmap incl. true auto-apply), demo/ (2 sample resumes PDF/DOCX + a
  seed script that loads sample jobs so the UI is clickable with zero keys).
- All code must actually run: builder proves it with the demo flow end to end
  (upload resume -> collect from no-key sources -> matches -> tailor via
  keyword fallback -> queue -> move status).
