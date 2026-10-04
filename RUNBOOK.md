# BenchPilot v1 — RUNBOOK

BenchPilot is your team's recruiter + bench-sales console. It keeps resumes
for your bench consultants, pulls jobs from the big boards, scores every
consultant against every job, tailors resumes to job descriptions, and runs
an apply queue with a placement pipeline.

## 1. Setup (5 minutes)

Requirements: Python 3.11+.

```bash
cd ~/workspace/benchpilot
./start.sh
```

`start.sh` creates a virtualenv, installs pinned dependencies, and serves
the app at **http://127.0.0.1:8741**. Leave that terminal open; stop with
Ctrl+C.

Optional: gate the whole app (UI + API) behind a shared password:

```bash
BENCHPILOT_PASSWORD='pick-a-strong-one' ./start.sh
```

The database lives at `data/benchpilot.db` (SQLite). Back it up by copying
that file.

## 2. Where to get API keys (all optional — the app works with zero keys)

| Source | What it covers | Where to get the key |
|---|---|---|
| Adzuna | Broad job aggregator (US). Also your Dice coverage — Dice has no public API (all endpoints 404 as of Oct 2026). | Free: https://developer.adzuna.com — sign up, copy **Application ID** and **API key** into Settings |
| RapidAPI JSearch | Aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter postings (these boards block scraping, so the API is the only reliable path). Working endpoint is `/search-v2`. | https://rapidapi.com — subscribe to the **JSearch** API (has a free tier), copy the key into Settings |
| LLM (any OpenAI-compatible API) | AI resume tailoring with strict no-invention rules. Without it, BenchPilot uses the built-in keyword tailoring, which works fine. | OpenAI / any compatible provider: base URL, API key, model name (e.g. `https://api.openai.com/v1`, `gpt-4o-mini`) |

Keys are stored in the local SQLite `settings` table, shown masked in the
UI/API, and never logged. No-key sources (RemoteOK, Remotive) work out of
the box.

## 3. Daily recruiter workflow

1. **Morning — collect jobs.** Jobs tab → "Run job collection" (1–3 min).
   It pulls from every enabled source for each of your search queries,
   dedupes, and re-scores all consultants automatically. Check the
   per-source status lines in Settings if a source looks empty.
2. **Review matches.** Matches tab → filter by consultant. Each match shows
   a 0–100 score with a breakdown (skill / title / location / recency) and
   the skills the consultant is missing for that job. Raise or lower the
   **match threshold** in Settings to tune volume.
3. **Tailor.** Click "Tailor resume" on a good match. You get a
   side-by-side original vs tailored view. If the tailoring engine detects
   any skill in the tailored text that isn't in the original resume, a
   warning banner appears and you must acknowledge it before queueing.
4. **Queue & apply (assisted).** "Save & queue" drops the application into
   the **Apply Queue** tab. Open the **Apply link**, submit the application
   on the job board with the downloaded tailored resume, then move the card
   to Applied. Track Screening → Interview → Offered → Placed (or
   Rejected/Withdrawn) from the same board. Notes live on each card.
5. **Found a great posting manually?** Jobs tab → "Import a posting URL".
   Paste any LinkedIn / Indeed / Dice / company-career link; BenchPilot
   fetches it, extracts the details, and scores your consultants against it
   immediately. This is the v1 path for boards that block automated
   collection.
6. **New consultant?** Consultants tab → Add, then "Upload resume"
   (PDF/DOCX/TXT). Skills are parsed instantly; matching runs on the next
   collection.

## 4. Hosting for the team

- **One recruiter, one machine:** run `./start.sh` as-is (localhost only).
- **Whole team on the office network:** run uvicorn bound to your machine
  instead of localhost, and set a shared password:
  ```bash
  BENCHPILOT_PASSWORD='team-secret' .venv/bin/python -m uvicorn \
    app.server:app --host 0.0.0.0 --port 8741
  ```
  Then the team opens `http://<your-machine-ip>:8741`. Keep the password
  strong — it is the only gate.
- **Always-on server:** put the uvicorn command behind systemd/supervisor
  on a small VPS, back up `data/benchpilot.db` nightly.

## 5. Honest notes & roadmap

- **"All jobs online"** = broad aggregation, not literal completeness.
  LinkedIn and Indeed block scraping; they are covered via the JSearch
  aggregator API and via manual URL import. Dice has no public JSON API at
  all — coverage comes via Adzuna + URL import.
- **"Auto-apply" v1 = assisted apply**: one-click apply links, tailored
  resumes, and a tracked pipeline. True hands-off auto-apply is roadmap,
  not v1: it needs each recruiter's per-site logins, breaks on CAPTCHAs
  and bot checks, and several boards' terms forbid it. The honest path is
  per-site browser automation with saved recruiter sessions, gated behind
  explicit per-application approval.
- **Resume tailoring never invents experience.** The LLM prompt and the
  keyword fallback both have a hard rule: only skills, employers, and dates
  present in the original resume may appear. Anything the engine flags as
  added must be acknowledged by a human before queueing.
- **Arbeitnow** ships as a bonus no-key source but is OFF by default —
  it's EU-leaning; enable it in Settings if you want it.
- Suggested next builds: email alerts on 85+ matches, duplicate-candidate
  detection across consultants, interview-prep briefs per application,
  client-submission tracking (which vendor got which resume when).

## 6. Project layout

```
app/server.py        FastAPI app + REST API
app/db.py            SQLite schema + data access (stdlib sqlite3)
app/skills.py        ~360-skill lexicon + phrase extraction
app/matcher.py       0-100 scoring (skill 70 / title 20 / location 10 + recency)
app/tailor.py        LLM tailoring + keyword fallback (no key needed)
app/sources/         adzuna, jsearch, remoteok, remotive, arbeitnow,
                     urlimport, dice (permanently disabled — no public API)
collector.py         scheduled-style collection: fetch -> dedupe -> match
frontend/            vanilla JS + CSS dashboard (no build step)
demo/                2 sample resumes + seed.py (zero-key demo data)
```
