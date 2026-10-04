# BenchPilot

Recruiter + bench-sales automation web app for staffing teams.

- **Resume vault** for bench consultants (PDF/DOCX/TXT upload, automatic skill extraction)
- **Job hunter** pulling postings from Adzuna, JSearch (RapidAPI → LinkedIn/Indeed/Glassdoor/ZipRecruiter), RemoteOK, Remotive, plus paste-any-URL import
- **Match engine** scoring every consultant against every job (0–100, with breakdown)
- **Resume tailor** rewriting resumes per job description — never invents experience
- **Apply queue** kanban: Queued → Applied → Screening → Interview → Offered → Placed

## Run it

```bash
./start.sh
```

Then open http://127.0.0.1:8741. Full setup guide, API key links, and team-hosting instructions are in [RUNBOOK.md](RUNBOOK.md).

## Deploying to Replit

Import this repo in Replit (Import from GitHub), set the run command to
`python -m uvicorn app.server:app --host 0.0.0.0 --port $PORT`, and deploy.
Set a `BENCHPILOT_PASSWORD` secret to gate the app.
