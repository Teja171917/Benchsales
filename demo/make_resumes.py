"""Generate the two demo resumes: one PDF (hand-written, stdlib only)
and one DOCX (python-docx). Run: python demo/make_resumes.py"""
from pathlib import Path

DEMO = Path(__file__).resolve().parent

PRIYA = """Priya Sharma
Senior Java Developer | Houston, TX | priya.sharma@example.com | (713) 555-0142

PROFESSIONAL SUMMARY
Senior Java Developer with 8 years of experience building microservices and
REST APIs for banking and logistics platforms. Strong background in Spring
Boot, AWS, and containerized deployments on Kubernetes.

TECHNICAL SKILLS
Java, Spring Boot, Microservices, REST APIs, Hibernate, JPA, Kafka, AWS,
Docker, Kubernetes, PostgreSQL, Maven, Jenkins, CI/CD, Git, Agile, JUnit

PROFESSIONAL EXPERIENCE
Senior Java Developer - NexaBank Solutions, Houston, TX (2019 - Present)
- Built payment microservices with Java and Spring Boot handling 2M transactions daily
- Designed REST APIs consumed by web and mobile clients
- Migrated monolith modules to microservices on AWS EKS with Docker and Kubernetes
- Implemented event-driven flows with Kafka for real-time fraud detection
- Set up Jenkins CI/CD pipelines cutting release time by 40 percent
- Wrote unit tests with JUnit and Mockito, raising coverage to 85 percent

Java Developer - LogiTrack Systems, Dallas, TX (2016 - 2019)
- Developed shipment tracking backend using Spring MVC and Hibernate
- Tuned PostgreSQL queries and added Redis caching to cut latency
- Participated in Agile ceremonies and code reviews with a team of six

EDUCATION
B.Tech, Computer Science - University of Houston (2016)
"""

ARUN_LINES = [
    ("Arun Patel", "title"),
    ("QA Automation Engineer | Remote | arun.patel@example.com | (832) 555-0198", ""),
    ("", ""),
    ("PROFESSIONAL SUMMARY", "h"),
    ("QA Automation Engineer with 6 years of experience building Selenium and "
     "API test frameworks for e-commerce and SaaS products. Skilled in Python, "
     "CI/CD integration, and performance testing.", ""),
    ("", ""),
    ("TECHNICAL SKILLS", "h"),
    ("Selenium, Python, Java, TestNG, Cypress, Postman, API Testing, Jenkins, "
     "CI/CD, SQL, JMeter, Git, Agile, Jira", ""),
    ("", ""),
    ("PROFESSIONAL EXPERIENCE", "h"),
    ("QA Automation Engineer - ShopKart Inc, Remote (2020 - Present)", "b"),
    ("- Built Selenium WebDriver framework with Python and TestNG for 400+ regression tests", ""),
    ("- Automated API testing with Postman and REST-assured, integrated into Jenkins CI/CD", ""),
    ("- Added Cypress end-to-end suites for checkout flows, cutting release defects by 35%", ""),
    ("- Ran JMeter performance tests and tuned SQL queries for reporting dashboards", ""),
    ("", ""),
    ("QA Analyst - DataBridge LLC, Houston, TX (2018 - 2020)", "b"),
    ("- Wrote manual and automated test cases for data pipeline releases", ""),
    ("- Used Jira for defect tracking across Agile sprints", ""),
    ("", ""),
    ("EDUCATION", "h"),
    ("B.S., Information Systems - Texas State University (2018)", ""),
]


def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, text: str) -> None:
    lines = [ln for ln in text.splitlines()]
    ops = ["BT", "/F1 11 Tf", "72 740 Td", "13.5 TL"]
    for ln in lines:
        ops.append(f"({_pdf_escape(ln)}) Tj")
        ops.append("T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1", "replace")

    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = [b"%PDF-1.4\n"]
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(sum(len(x) for x in out))
        out.append(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref_pos = sum(len(x) for x in out)
    out.append(b"xref\n0 %d\n" % (len(objs) + 1))
    out.append(b"0000000000 65535 f \n")
    for off in offsets:
        out.append(b"%010d 00000 n \n" % off)
    out.append(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
               % (len(objs) + 1, xref_pos))
    path.write_bytes(b"".join(out))


def write_docx(path: Path) -> None:
    from docx import Document
    doc = Document()
    for text, kind in ARUN_LINES:
        if kind == "title":
            doc.add_heading(text, level=0)
        elif kind == "h":
            doc.add_heading(text, level=1)
        elif kind == "b":
            doc.add_paragraph().add_run(text).bold = True
        else:
            doc.add_paragraph(text)
    doc.save(path)


if __name__ == "__main__":
    write_pdf(DEMO / "resume-priya-sharma.pdf", PRIYA)
    write_docx(DEMO / "resume-arun-patel.docx")
    print("wrote demo resumes")
