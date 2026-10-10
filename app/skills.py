"""Curated skill lexicon + phrase extraction for BenchPilot."""
import re

# ~360 entries: languages, frameworks, frontend, data, cloud/devops, tools,
# testing, methodologies, mobile, misc.
SKILLS = [
    # languages
    "java", "python", "javascript", "typescript", "c#", "c++", "c", "go",
    "golang", "ruby", "php", "swift", "kotlin", "scala", "rust", "perl",
    "r language", "matlab", "sql", "pl/sql", "t-sql", "bash", "powershell",
    "groovy", "dart", "elixir", "haskell", "lua", "vba", "sas",
    # jvm / backend frameworks
    "spring boot", "spring", "spring mvc", "spring security", "hibernate",
    "jpa", "microservices", "rest api", "restful", "graphql", "grpc",
    "soap", "jax-rs", "servlets", "jsp", "struts", "node.js", "express.js",
    "express", "django", "flask", "fastapi", ".net", ".net core", "asp.net",
    "asp.net core", "entity framework", "laravel", "rails", "ruby on rails",
    "spring cloud", "kafka", "rabbitmq", "activemq", "mqtt", "websockets",
    "oauth", "oauth2", "jwt", "saml", "ldap", "okta", "keycloak",
    # frontend
    "react", "angular", "vue", "vue.js", "next.js", "nuxt.js", "redux",
    "html", "html5", "css", "css3", "sass", "scss", "less", "bootstrap",
    "tailwind css", "material ui", "jquery", "ajax", "responsive design",
    "typescript", "webpack", "vite", "babel", "npm", "yarn", "pnpm",
    # data
    "postgresql", "mysql", "oracle", "sql server", "mongodb", "cassandra",
    "redis", "elasticsearch", "dynamodb", "cosmos db", "snowflake",
    "bigquery", "redshift", "databricks", "spark", "apache spark", "hadoop",
    "hive", "airflow", "dbt", "kafka streams", "etl", "data warehousing",
    "data modeling", "pandas", "numpy", "scikit-learn", "tensorflow",
    "pytorch", "keras", "machine learning", "deep learning", "nlp",
    "computer vision", "llm", "langchain", "openai", "tableau", "power bi",
    "looker", "qlik", "ssis", "ssrs", "informatica", "talend",
    # cloud / devops
    "aws", "amazon web services", "azure", "microsoft azure", "gcp",
    "google cloud", "docker", "kubernetes", "k8s", "openshift", "terraform",
    "cloudformation", "ansible", "puppet", "chef", "jenkins", "gitlab ci",
    "github actions", "circleci", "travis ci", "azure devops", "ci/cd",
    "argo cd", "helm", "prometheus", "grafana", "elk", "splunk",
    "datadog", "new relic", "nginx", "apache", "tomcat", "iis",
    "load balancing", "lambda", "ec2", "s3", "rds", "eks", "aks", "gke",
    "vpc", "iam", "cloudwatch", "serverless", "microservices architecture",
    "service mesh", "istio", "consul", "vault",
    # tools / platforms
    "git", "github", "gitlab", "bitbucket", "svn", "jira", "confluence",
    "trello", "asana", "slack", "microsoft teams", "sharepoint", "servicenow",
    "salesforce", "sap", "oracle ebs", "workday", "peoplesoft", "hubspot",
    "zendesk", "postman", "swagger", "openapi", "insomnia", "figma",
    "adobe xd", "sketch", "photoshop", "illustrator", "vs code",
    "intellij", "eclipse", "visual studio", "pycharm", "android studio",
    "xcode", "maven", "gradle", "ant", "nuget", "pip", "artifactory",
    "nexus", "sonarqube", "veracode", "checkmarx", "snyk",
    # testing
    "selenium", "selenium webdriver", "cypress", "playwright", "testng",
    "junit", "pytest", "nunit", "xunit", "mocha", "jest", "jasmine",
    "karma", "cucumber", "bdd", "tdd", "appium", "jmeter", "loadrunner",
    "gatling", "k6", "postman", "api testing", "performance testing",
    "load testing", "regression testing", "smoke testing", "uat",
    "test automation", "qa automation", "manual testing",
    "restassured", "soapui", "allure", "rally", "istqb", "test strategy",
    "defect management", "test management", "shift-left testing",
    # ai / llm
    "claude api", "generative ai", "prompt engineering", "prompt testing",
    "llm testing", "rag", "vector database", "hugging face",
    # methodologies / practices
    "agile", "scrum", "kanban", "safe", "waterfall", "devops", "sre",
    "site reliability", "code review", "pair programming", "ci", "cd",
    "continuous integration", "continuous deployment", "gitflow",
    "trunk based development", "a/b testing", "feature flags",
    # mobile
    "android", "ios", "react native", "flutter", "xamarin", "swiftui",
    "jetpack compose", "cordova", "ionic",
    # security / networking
    "cybersecurity", "penetration testing", "owasp", "vulnerability assessment",
    "firewall", "vpn", "dns", "tcp/ip", "ssl", "tls", "encryption",
    # misc / soft-tech
    "linux", "unix", "windows server", "macos", "shell scripting",
    "json", "xml", "yaml", "markdown", "uml", "design patterns",
    "solid principles", "oop", "functional programming", "multithreading",
    "concurrency", "caching", "message queue", "event driven",
    "domain driven design", "clean architecture", "technical writing",
    "documentation", "mentoring", "stakeholder management",
]

# alias -> canonical (must exist in SKILLS)
ALIASES = {
    "k8s": "kubernetes",
    "node": "node.js",
    "nodejs": "node.js",
    "reactjs": "react",
    "react.js": "react",
    "vuejs": "vue",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "mssql": "sql server",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "apis": "rest api",
    "ci": "continuous integration",
    "rest assured": "restassured",
    "rest-assured": "restassured",
    "ms teams": "microsoft teams",
    "gen ai": "generative ai",
    "genai": "generative ai",
}

_SKILL_SET = frozenset(SKILLS)

_COMPILED: dict[str, re.Pattern] = {}


def _pattern(skill: str) -> re.Pattern:
    if skill not in _COMPILED:
        # (?<![...]) guards avoid matching inside longer tokens, e.g. "java"
        # inside "javascript"; also handles symbols like c++, c#, .net, ci/cd.
        # Note: "." is only in the lookbehind, not the lookahead - a trailing
        # period is a sentence end ("knows Playwright.") and must still match.
        _COMPILED[skill] = re.compile(
            r"(?<![A-Za-z0-9_+#.\-/])" + re.escape(skill) + r"(?![A-Za-z0-9_+#\-/])"
        )
    return _COMPILED[skill]


def normalize(text: str) -> str:
    t = text.lower()
    t = t.replace("c plus plus", "c++").replace("c sharp", "c#")
    return t


# Skills learned automatically from the resumes (see app/autolearn.py).
# They live in the database; this set is a copy kept in memory.
_LEARNED: frozenset = frozenset()


def set_learned(skills) -> bool:
    """Replace the learned vocabulary. Returns True if it changed."""
    global _LEARNED
    new = frozenset(s.strip().lower() for s in skills if s and s.strip())
    if new == _LEARNED:
        return False
    _LEARNED = new
    return True


def learned() -> frozenset:
    return _LEARNED


def is_known(skill: str) -> bool:
    s = (skill or "").strip().lower()
    return s in _LEARNED or s in ALIASES or s in _SKILL_SET


def extract_skills(text: str) -> list[str]:
    """Return sorted list of canonical skills found in text (case-insensitive)."""
    if not text:
        return []
    t = normalize(text)
    found: set[str] = set()
    for skill in SKILLS:
        if _pattern(skill).search(t):
            found.add(skill)
    for skill in _LEARNED:
        if _pattern(skill).search(t):
            found.add(skill)
    # aliases
    for alias, canonical in ALIASES.items():
        if _pattern(alias).search(t):
            found.add(canonical)
    return sorted(found)


def requirements_skills(description: str) -> set[str]:
    """Skills appearing under a Requirements/Qualifications heading (naive)."""
    if not description:
        return set()
    lines = description.splitlines()
    in_req = False
    buf: list[str] = []
    enders = re.compile(
        r"^(benefits|about (us|the)|nice to have|preferred|responsibilities|"
        r"what we offer|compensation|perks|how to apply|equal opportunity)",
        re.I,
    )
    for line in lines:
        s = line.strip()
        if not in_req:
            if re.match(
                r"^(requirements|qualifications|what you.?ll bring|must haves?|"
                r"required skills|minimum qualifications|basic qualifications)",
                s, re.I,
            ):
                in_req = True
            continue
        if enders.match(s) or s.lower().startswith("preferred"):
            break
        buf.append(line)
    return set(extract_skills("\n".join(buf)))


# Canonical (lowercase) skill -> how it should appear on a resume.
_DISPLAY_OVERRIDES = {
    "c#": "C#", "c++": "C++", "ci/cd": "CI/CD", "ci": "CI", "cd": "CD",
    "t-sql": "T-SQL", "pl/sql": "PL/SQL", "sql server": "SQL Server",
    "r language": "R", "typescript": "TypeScript", "javascript": "JavaScript",
    "rest api": "REST API", "restful": "RESTful", "restassured": "RestAssured",
    "selenium webdriver": "Selenium WebDriver", "testng": "TestNG",
    "junit": "JUnit", "pytest": "Pytest", "nunit": "NUnit", "xunit": "xUnit",
    "soapui": "SoapUI", "postgresql": "PostgreSQL", "mysql": "MySQL",
    "mongodb": "MongoDB", "dynamodb": "DynamoDB", "cosmos db": "Cosmos DB",
    "github": "GitHub", "gitlab": "GitLab", "bitbucket": "Bitbucket",
    "azure devops": "Azure DevOps", "microsoft azure": "Microsoft Azure",
    "google cloud": "Google Cloud", "amazon web services": "Amazon Web Services",
    "power bi": "Power BI", "material ui": "Material UI", "tailwind css": "Tailwind CSS",
    "node.js": "Node.js", "vue.js": "Vue.js", "next.js": "Next.js", "nuxt.js": "Nuxt.js",
    "express.js": "Express.js", ".net": ".NET", ".net core": ".NET Core",
    "asp.net": "ASP.NET", "asp.net core": "ASP.NET Core",
    "spring boot": "Spring Boot", "spring mvc": "Spring MVC",
    "spring security": "Spring Security", "kafka streams": "Kafka Streams",
    "apache spark": "Apache Spark", "machine learning": "Machine Learning",
    "deep learning": "Deep Learning", "computer vision": "Computer Vision",
    "generative ai": "Generative AI", "claude api": "Claude API",
    "prompt engineering": "Prompt Engineering", "hugging face": "Hugging Face",
    "openai": "OpenAI", "langchain": "LangChain", "llm": "LLM", "nlp": "NLP",
    "rag": "RAG", "uat": "UAT", "bdd": "BDD", "tdd": "TDD",
    "owasp": "OWASP", "iam": "IAM", "vpc": "VPC", "ec2": "EC2", "s3": "S3",
    "rds": "RDS", "eks": "EKS", "aks": "AKS", "gke": "GKE",
    "jwt": "JWT", "oauth": "OAuth", "oauth2": "OAuth2", "saml": "SAML",
    "ldap": "LDAP", "okta": "Okta", "keycloak": "Keycloak",
    "tcp/ip": "TCP/IP", "ssl": "SSL", "tls": "TLS", "dns": "DNS", "vpn": "VPN",
    "istqb": "ISTQB", "cpsat": "CPSAT", "safe": "SAFe", "sre": "SRE",
    "a/b testing": "A/B Testing", "elk": "ELK",
    "site reliability": "Site Reliability", "trunk based development": "Trunk-Based Development",
    "k8s": "K8s", "argo cd": "Argo CD",
    "vs code": "VS Code", "intellij": "IntelliJ", "pycharm": "PyCharm",
    "visual studio": "Visual Studio", "android studio": "Android Studio",
    "xcode": "Xcode", "macos": "macOS",
}


def display_name(skill: str) -> str:
    """How a canonical (lowercase) skill should appear on a resume.

    "playwright" -> "Playwright", "ci/cd" -> "CI/CD". Unknown skills fall
    back to title-casing.
    """
    s = (skill or "").strip()
    if not s:
        return s
    low = s.lower()
    if low in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[low]
    return " ".join(w.capitalize() for w in s.split())
