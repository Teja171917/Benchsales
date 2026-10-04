"""Seed BenchPilot with demo data so the UI is clickable with zero API keys.

Creates 2 demo consultants (if none exist), attaches the demo resumes,
inserts 6 sample jobs, and runs the matcher.

Run:  python demo/seed.py   (from the project root, venv active)
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import db
from app import matcher
from app.skills import extract_skills

SAMPLE_JOBS = [
    {
        "source": "seed", "source_id": "seed-1",
        "title": "Senior Java Developer", "company": "GulfPay Financial",
        "location": "Houston, TX", "remote_flag": 0,
        "url": "https://example.com/jobs/gulfpay-java",
        "description": """Senior Java Developer - GulfPay Financial, Houston TX.

Requirements:
- 6+ years Java and Spring Boot building microservices
- Strong REST API design experience
- AWS, Docker, Kubernetes in production
- Kafka for event-driven systems
- CI/CD with Jenkins, PostgreSQL

Nice to have: React, Terraform.""",
        "posted_at": "2026-10-02T09:00:00+00:00", "salary": "$130k - $150k",
        "employment_type": "Full-time",
    },
    {
        "source": "seed", "source_id": "seed-2",
        "title": "QA Automation Engineer", "company": "Nimbus Retail",
        "location": "Remote", "remote_flag": 1,
        "url": "https://example.com/jobs/nimbus-qa",
        "description": """QA Automation Engineer (Remote).

Requirements:
- Selenium WebDriver with Python or Java
- API testing with Postman
- CI/CD pipelines (Jenkins or GitHub Actions)
- SQL for test data validation
- Agile team experience

Preferred: Cypress, JMeter.""",
        "posted_at": "2026-10-01T12:00:00+00:00", "salary": "$100k - $120k",
        "employment_type": "Full-time",
    },
    {
        "source": "seed", "source_id": "seed-3",
        "title": "Backend Python Developer", "company": "Datawise Analytics",
        "location": "Remote", "remote_flag": 1,
        "url": "https://example.com/jobs/datawise-python",
        "description": """Backend Python Developer (Remote).

Requirements:
- Python, FastAPI or Django
- PostgreSQL and Redis
- Docker, AWS
- REST API development

Nice to have: Kubernetes, Airflow.""",
        "posted_at": "2026-09-28T08:00:00+00:00", "salary": "$120k - $140k",
        "employment_type": "Contract",
    },
    {
        "source": "seed", "source_id": "seed-4",
        "title": "DevOps Engineer", "company": "PetroCloud Energy",
        "location": "Houston, TX", "remote_flag": 0,
        "url": "https://example.com/jobs/petrocloud-devops",
        "description": """DevOps Engineer - Houston, TX.

Requirements:
- Kubernetes administration (EKS/AKS)
- Terraform and CI/CD (Jenkins, GitLab CI)
- AWS networking and IAM
- Prometheus and Grafana monitoring

Nice to have: Python scripting.""",
        "posted_at": "2026-10-03T10:00:00+00:00", "salary": "$135k - $155k",
        "employment_type": "Full-time",
    },
    {
        "source": "seed", "source_id": "seed-5",
        "title": "Java Microservices Developer", "company": "TransLogix",
        "location": "Dallas, TX", "remote_flag": 0,
        "url": "https://example.com/jobs/translogix-java",
        "description": """Java Microservices Developer - Dallas, TX.

Requirements:
- Java 11+, Spring Boot, microservices architecture
- REST APIs, JPA/Hibernate
- Docker and CI/CD
- SQL Server or PostgreSQL""",
        "posted_at": "2026-09-25T09:00:00+00:00", "salary": "$115k - $135k",
        "employment_type": "Contract",
    },
    {
        "source": "seed", "source_id": "seed-6",
        "title": "Senior Test Automation Engineer", "company": "MediSoft Health",
        "location": "Remote", "remote_flag": 1,
        "url": "https://example.com/jobs/medisoft-test",
        "description": """Senior Test Automation Engineer (Remote).

Requirements:
- Selenium and Cypress test automation
- Java or Python
- API testing, Jenkins CI/CD
- Performance testing with JMeter""",
        "posted_at": "2026-10-02T14:00:00+00:00", "salary": "$110k - $130k",
        "employment_type": "Full-time",
    },
]

DEMO_PEOPLE = [
    {"name": "Priya Sharma", "email": "priya.sharma@example.com",
     "phone": "(713) 555-0142", "location": "Houston, TX",
     "visa_status": "H1B", "notes": "Demo consultant",
     "resume_file": "resume-priya-sharma.pdf"},
    {"name": "Arun Patel", "email": "arun.patel@example.com",
     "phone": "(832) 555-0198", "location": "Houston, TX",
     "visa_status": "GC", "notes": "Demo consultant",
     "resume_file": "resume-arun-patel.docx"},
]


def main():
    db.init_db()
    demo_dir = Path(__file__).resolve().parent
    import io

    if not db.list_consultants():
        for p in DEMO_PEOPLE:
            c = db.create_consultant(p)
            rp = demo_dir / p["resume_file"]
            if rp.exists():
                raw = rp.read_bytes()
                ext = rp.suffix.lower()
                if ext == ".pdf":
                    from pypdf import PdfReader
                    text = "\n".join(
                        (pg.extract_text() or "")
                        for pg in PdfReader(io.BytesIO(raw)).pages)
                elif ext == ".docx":
                    from docx import Document
                    doc = Document(io.BytesIO(raw))
                    text = "\n".join([para.text for para in doc.paragraphs])
                else:
                    text = raw.decode("utf-8", "ignore")
                db.upsert_resume(c["id"], rp.name, text.strip(),
                                 extract_skills(text))
                print(f"consultant {p['name']}: resume parsed, "
                      f"{len(extract_skills(text))} skills")
            else:
                print(f"WARNING: missing {rp} — run demo/make_resumes.py first")

    new_jobs = sum(1 for j in SAMPLE_JOBS if db.insert_job(j))
    print(f"inserted {new_jobs} new sample jobs")

    new_matches = matcher.run_all()
    print(f"created {new_matches} new matches")
    print("seed complete")


if __name__ == "__main__":
    main()
