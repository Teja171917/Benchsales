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
| Adzuna | Broad job aggregator (US). Partial Dice-style coverage — Dice has no public API; use the Portal links for Dice itself. | Free: https://developer.adzuna.com — sign up, copy **Application ID** and **API key** into Settings |
| RapidAPI JSearch | Aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter postings (these boards block scraping, so the API is the only reliable path). Working endpoint is `/search-v2`. | https://rapidapi.com — subscribe to the **JSearch** API (has a free tier), copy the key into Settings |
| LLM (any OpenAI-compatible API) | AI resume tailoring with strict no-invention rules. Without it, BenchPilot uses the built-in keyword tailoring, which works fine. | OpenAI / any compatible provider: base URL, API key, model name (e.g. `https://api.openai.com/v1`, `gpt-4o-mini`) |

Keys are stored in the local SQLite `settings` table, shown masked in the
UI/API, and never logged. No-key sources (RemoteOK, Remotive) work out of
the box.

## 2b. USA market: Full-time, C2C, W2

- **Employment type chips** (Jobs and Matches tabs): Full-time, C2C, W2,
  Contract, 1099, Contract-to-hire, Part-time. A job passes if it has *any*
  ticked tag. "Include jobs with no type listed" keeps postings where nothing
  could be detected (most aggregator listings) — untick it for a strict view.
- **How a job gets its tags:** the board's own type field plus the title and
  description. "Open to C2C or W2" tags both; "No C2C", "C2C not accepted" and
  "W2 only" are respected. Boilerplate like "benefits for full-time
  employees" is ignored. Detection is keyword-based — always read the posting.
- **Consultant "Open to"** (Consultants tab -> Edit): tick the engagement types
  a consultant takes. Jobs that explicitly list only *other* types are not
  matched to them; jobs with no stated type still match. Leave blank for all.
- **Settings -> USA market:** "USA jobs only" drops postings whose location
  clearly names another country (blank / "Remote" are kept). "Employment types
  to collect" steers the Adzuna and JSearch queries (C2C/W2/1099 are requested
  as "contractor" from JSearch).
- **Portal links** (Jobs -> Live job search -> Portal links): opens Dice,
  Indeed, LinkedIn, ZipRecruiter, Glassdoor, Monster, CareerBuilder and Google
  Jobs with your title, location and type filters filled in. Dice, Indeed and
  LinkedIn block automated collection, so this is the supported way in; sign
  in to each in your own browser. Filter parameters for Dice/Indeed/LinkedIn
  could not be tested from the build environment — open each once to confirm.
  **Settings -> Check portal access** tests whether the *server* can reach each
  portal (useful for URL import).

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
  all — use the Portal links and URL import (Adzuna adds some coverage).
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
app/emptype.py       Full-time / C2C / W2 / 1099 / C2H detection from type + text
app/usa.py           USA-only location filter
app/portals.py       pre-filled Dice / Indeed / LinkedIn... search links + access check
app/tailor.py        LLM tailoring + keyword fallback (no key needed)
app/sources/         adzuna, jsearch, remoteok, remotive, arbeitnow,
                     urlimport, dice (permanently disabled — no public API)
collector.py         scheduled-style collection: fetch -> dedupe -> match
frontend/            vanilla JS + CSS dashboard (no build step)
demo/                2 sample resumes + seed.py (zero-key demo data)
tests/               unit tests (python -m unittest discover -s tests)
```

## Automatic mode (no one has to press anything)

While the app is running it looks after itself:

- **Searches come from the resumes.** Each consultant's headline role (for example "QA Automation Engineer") + their city, and "Remote", become the job searches. Upload a new resume and the searches change, and a job search starts right away.
- **Skills are learned.** New tool names in a resume's Skills section are added to the skill list automatically (Settings > Fully automatic mode shows them; click x to remove one for good). Stored resume skills and existing match scores are recalculated when that happens. Matches are never deleted.
- **Refresh schedule survives restarts.** The time of the last run is saved, so a restart does not reset the clock.
- **Free-key safety.** Adzuna's free key allows 250 calls/day and 2,500/month. The app counts its calls, stays under "Adzuna calls per day" (default 80) and slows the schedule down when needed.

Still needs a person: changing the code, and keeping the app awake. A free Replit app can sleep when nobody visits; an always-on plan (or a small server) keeps the schedule running 24/7.

## Agent fixes and the AI resume update

- **Compliance runs first** now, so Tailor and Outreach never draft for a match that was just quarantined. Quarantined matches are skipped by both.
- The Office runs once a day **after** the job refresh. If the app slept for more than a day, Scout looks back to the last run.
- **Market Analyst** queries are kept in their own list and the collector always reserves room for the newest two, so they are really searched (before, they could be squeezed out by the consultants' own searches).
- **Tailor** drafts for matches at or above the score in Settings (default **65**, **10 drafts a day**). Each draft shows what the score could become if a person confirms the missing skills (for example `70.7 -> 82.3`). Agents never add a skill themselves.
- With no AI key the draft only re-orders skills and bullets. For real AI rewriting fill the three **LLM** fields in Settings. The AI is told never to add skills, employers or dates.
- **Add resumes** (Consultants tab): choose many resume files at once; each creates or updates the consultant from the name, email and city in the resume, then skills, job search and matching start by themselves.

## Resume folder (Google Drive) - resumes come in by themselves

1. Put the resumes in one Google Drive folder. Share it: **Share > General access > Anyone with the link** (viewer).
2. Get a free Google API key: `console.cloud.google.com` > new project > **APIs & Services > Library > Google Drive API > Enable** > **Credentials > Create credentials > API key**.
3. In the site: **Settings > Resume folder (Google Drive)**: paste the folder link and the key, press **Save settings**, then **Read the folder now**.
4. From then on the site checks the folder about every hour. Each new or changed resume creates/updates the consultant (name, email, city from the resume), then skills, job search, matching and the agents follow.

Notes: only files directly inside the folder are read (PDF, Word, text, Google Docs); subfolders are skipped. Nothing is changed or deleted in Drive. Up to 25 files are read per check (the rest on the next one). A file that cannot be read is reported once and not retried until it changes. Resumes stay in this app's database only - never put real resumes in the GitHub repo.

## AI-checked resume reading (Add resumes)

- **Add resumes** takes any number of files. For each one the AI (the LLM set in Settings) reads the name, email, phone and city. Plain code then double-checks every value against the resume text: a value that is not literally in the resume is thrown away. The AI only reads; it never writes into a resume.
- A consultant gets **Needs a quick check** only when a check fails (no valid email, name not confirmed, only one name found, AI unsure, AI and rule reader disagree). The card has **Looks right** and **Fix it** buttons. Saving an edit also clears the flag.
- No AI key? The same checks run on the simple rule reader, so more resumes are flagged. The resume text is sent to the AI provider when a key is set - tell the team before using real resumes.
- The Google Drive folder import (Settings) uses the same reader.

## Keep the data safe (free): backup + Secrets

Problem: a published Replit site runs on a disk that is **wiped on every Republish** (and when the site sleeps). Consultants, resumes, matches and keys saved on that disk disappear.

Fix (free), two parts:

1. **Backup (App Storage).** `app/persist.py` copies the database to Replit App Storage every 20 seconds (only when it changed) and puts it back at start-up. Settings → *Data backup* shows **ON/OFF**, the last save time, and a *Back up now* button.
   - Replit: left tools → **App Storage** → **Create bucket** → make sure it is the app's default bucket.
   - `requirements.txt` already lists `replit-object-storage`.
   - Deployment settings: keep **max machines = 1**.
2. **Secrets (keys).** In Replit → **Secrets** add: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `RAPIDAPI_KEY` (optional), `LLM_BASE_URL` (`https://api.groq.com/openai/v1`), `LLM_API_KEY`, `LLM_MODEL` (`llama-3.3-70b-versatile`), and `BENCHPILOT_PASSWORD`. A key typed in Settings wins; an empty one is filled from the Secret.

Check: add a consultant → wait 1 minute → Settings shows "Last saved" → Republish → the consultant is still there.
Limit: changes made in the last ~20 seconds before a restart can be lost.
