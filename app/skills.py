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
    "trello", "asana", "slack", "teams", "sharepoint", "servicenow",
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
}

_COMPILED: dict[str, re.Pattern] = {}


def _pattern(skill: str) -> re.Pattern:
    if skill not in _COMPILED:
        # (?<![...]) guards avoid matching inside longer tokens, e.g. "java"
        # inside "javascript"; also handles symbols like c++, c#, .net, ci/cd.
        _COMPILED[skill] = re.compile(
            r"(?<![A-Za-z0-9_+#.\-/])" + re.escape(skill) + r"(?![A-Za-z0-9_+#.\-/])"
        )
    return _COMPILED[skill]


def normalize(text: str) -> str:
    t = text.lower()
    t = t.replace("c plus plus", "c++").replace("c sharp", "c#")
    return t


def extract_skills(text: str) -> list[str]:
    """Return sorted list of canonical skills found in text (case-insensitive)."""
    if not text:
        return []
    t = normalize(text)
    found: set[str] = set()
    for skill in SKILLS:
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
