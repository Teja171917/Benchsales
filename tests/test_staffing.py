"""Staffing-firms source: the watchlist and the SmartRecruiters adapter."""
import unittest
from unittest import mock

from app.sources import smartrecruiters as sr


_POSTINGS = {
    "totalFound": 3,
    "content": [
        {"id": "101", "name": "Data Engineer", "releasedDate": "2026-10-20T00:00:00.000Z",
         "location": {"city": "Austin", "region": "TX", "country": "us",
                      "remote": False, "fullLocation": "Austin, TX, United States"},
         "typeOfEmployment": {"id": "contract", "label": "Contract"}},
        {"id": "102", "name": "Marketing Manager", "releasedDate": "2026-10-21T00:00:00.000Z",
         "location": {"city": "Dallas", "region": "TX", "country": "us",
                      "remote": True, "fullLocation": "Dallas, TX, United States"},
         "typeOfEmployment": {"id": "full_time", "label": "Full-time"}},
        {"id": "103", "name": "Data Analyst", "releasedDate": "2026-10-22T00:00:00.000Z",
         "location": {"city": "Toronto", "region": "ON", "country": "ca",
                      "remote": False, "fullLocation": "Toronto, ON, Canada"},
         "typeOfEmployment": {"id": "contract", "label": "Contract"}},
    ],
}
_DETAIL = {"jobAd": {"sections": {
    "jobDescription": {"text": "<p>Build <b>pipelines</b>.</p>"},
    "qualifications": {"text": "<p>Python, SQL.</p>"}}}}


class StaffingFirmsTests(unittest.TestCase):
    def test_watchlist_loaded(self):
        firms = sr.firms()
        self.assertEqual(len(firms), 202)
        live = sr.sr_firms()
        self.assertGreaterEqual(len(live), 15)
        for f in live:
            self.assertTrue(f["identifier"])
            self.assertIn("smartrecruiters", f["ats"].lower())

    def test_fetch_filters_us_and_title_and_fills_description(self):
        def fake_get(url, ttl=300, **kw):
            if url.endswith("/postings/101"):
                return _DETAIL
            if "/postings?" in url:
                return _POSTINGS
            raise AssertionError(f"unexpected url {url}")
        with mock.patch.object(sr, "sr_firms",
                               return_value=[{"company": "Collabera",
                                              "identifier": "Collabera6"}]), \
             mock.patch.object(sr, "get_json_cached", side_effect=fake_get):
            jobs = sr.fetch({"title": "Data Engineer"}, {})
        # the Toronto posting is dropped (non-US); the Marketing title misses
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j["source"], "smartrecruiters")
        self.assertEqual(j["source_id"], "Collabera6:101")
        self.assertEqual(j["company"], "Collabera")
        self.assertEqual(j["employment_type"], "Contract")
        self.assertIn("pipelines", j["description"])
        self.assertIn("Python, SQL", j["description"])
        self.assertNotIn("_sr", j)

    def test_one_firm_outage_does_not_kill_the_feed(self):
        def fake_get(url, ttl=300, **kw):
            if "BadFirm" in url:
                raise RuntimeError("boom")
            if "/postings?" in url:
                return _POSTINGS
            return _DETAIL
        firms = [{"company": "Bad", "identifier": "BadFirm"},
                 {"company": "Collabera", "identifier": "Collabera6"}]
        with mock.patch.object(sr, "sr_firms", return_value=firms), \
             mock.patch.object(sr, "get_json_cached", side_effect=fake_get):
            jobs = sr.fetch({"title": "Data"}, {})
        self.assertTrue(jobs)
        self.assertTrue(all(j["company"] == "Collabera" for j in jobs))

    def test_registered_in_collectors(self):
        import collector
        from app import server
        self.assertIn(sr, collector.SOURCES)
        self.assertIn(sr, server.SOURCES)
        self.assertIn(sr, server.LIVE_SOURCES)


if __name__ == "__main__":
    unittest.main()
