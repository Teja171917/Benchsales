"""Job-market city list: the Matches city filter is built from the whole
job pool — every real US city with its job count — not from whichever
matches happen to be on screen."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, db


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{pw}".encode()).decode()}


class JobCitiesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_db, self._old_acc = db.DB_PATH, accounts.ACCOUNTS_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        accounts.ACCOUNTS_PATH = Path(self.tmp.name) / "accounts.db"
        accounts._ready = False
        accounts.init_accounts()
        self._old_env = {k: os.environ.get(k) for k in
                         ("BENCHPILOT_COMPANIES", "BENCHPILOT_PASSWORD",
                          "BENCHPILOT_USERNAME")}
        os.environ["BENCHPILOT_COMPANIES"] = json.dumps(
            {"Acme Staffing": {"username": "acme", "password": "acme-pw"}})
        os.environ["BENCHPILOT_PASSWORD"] = "main-pw"
        os.environ.pop("BENCHPILOT_USERNAME", None)
        locations = [
            ("Java Dev", "Houston, TX"), ("Java Dev", "Houston, TX"),
            ("Web Dev", "Houston, TX"), ("Data Eng", "Austin, TX"),
            ("SRE Role", "Trammells, Harris County"),
            ("SRE Role", "Grand Central, Manhattan"),
            ("SRE Role", "Houston, Harris County"),
            ("SRE Role", "Old Sixth Ward, Houston"),
            ("SRE Role", "Manhattan, NY"),
            ("Dev Role", "Texas, TX"), ("Dev Role", "Washington, DC"),
            ("Dev Role", "Washington, WA"),
            ("Data Eng", "Remote - Dallas, TX"), ("QA Lead", "Remote"),
            ("QA Lead", "Texas"), ("PM Role", "United States"),
            ("PM Role", ""), ("SRE Role", "New York, NY"),
        ]
        for i, (title, loc) in enumerate(locations):
            db.insert_job({
                "source": "t", "source_id": f"s{i}", "title": title,
                "company": f"Co{i}", "location": loc,
                "remote_flag": 1 if loc.startswith("Remote") else 0,
                "url": "", "description": "role", "posted_at": "",
                "salary": "", "employment_type": ""})
        from fastapi.testclient import TestClient
        from app import server
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def tearDown(self):
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_cities_cover_the_whole_pool_with_counts(self):
        cities = {c["city"]: c["jobs"] for c in db.job_cities()}
        self.assertEqual(cities, {"Houston": 5, "Austin": 1,
                                  "Dallas": 1, "New York": 3,
                                  "Washington": 1})
        ordered = [c["city"] for c in db.job_cities()]
        self.assertEqual(ordered[0], "Houston")      # busiest first

    def test_city_of_location_formats(self):
        confirmed = {"Houston", "Austin"}
        f = db.city_of_location
        self.assertEqual(f("Houston, TX", confirmed), "Houston")
        self.assertEqual(f("Houston, Harris County", confirmed), "Houston")
        self.assertEqual(f("Trammells, Harris County", confirmed), "")
        self.assertEqual(f("Old Sixth Ward, Houston", confirmed), "Houston")
        self.assertEqual(f("Grand Central, Manhattan", confirmed),
                         "New York")
        self.assertEqual(f("Remote - Dallas, TX", confirmed), "Dallas")
        self.assertEqual(f("Texas", confirmed), "")
        self.assertEqual(f("Texas, TX", confirmed), "")
        self.assertEqual(f("Washington, DC", confirmed), "Washington")
        self.assertEqual(f("Washington, WA", confirmed), "")
        self.assertEqual(f("", confirmed), "")

    def test_endpoint(self):
        h = _basic("x", "main-pw")
        r = self.client.get("/api/jobs/cities", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()[0]["city"], "Houston")
        r = self.client.get("/api/jobs/cities")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
