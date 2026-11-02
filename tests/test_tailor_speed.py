"""Tailor must never stall: a placeholder AI key skips the provider
call entirely (it used to burn the full 90s timeout on every click
before falling back), a real key gets a short timeout, and the market
demand scan behind the tailor response is cached per workspace."""
import tempfile
import unittest
from pathlib import Path

from app import db, market, tailor


class FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "rewritten"}}]}


class LlmShortCircuitTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._old_post = tailor.requests.post

        def fake_post(*a, **kw):
            self.calls.append(kw)
            return FakeResp()
        tailor.requests.post = fake_post

    def tearDown(self):
        tailor.requests.post = self._old_post

    def test_placeholder_key_never_calls_the_provider(self):
        out = tailor._llm_tailor("resume", "jd", {
            "llm_base_url": "https://api.groq.com/openai/v1",
            "llm_api_key": "short123", "llm_model": "m"})
        self.assertIsNone(out)
        self.assertEqual(self.calls, [])

    def test_real_key_calls_with_a_short_timeout(self):
        out = tailor._llm_tailor("resume", "jd", {
            "llm_base_url": "https://api.groq.com/openai/v1",
            "llm_api_key": "gsk_" + "x" * 40, "llm_model": "m"})
        self.assertEqual(out, "rewritten")
        self.assertEqual(len(self.calls), 1)
        self.assertLessEqual(self.calls[0]["timeout"], 20)

    def test_missing_config_stays_silent(self):
        self.assertIsNone(tailor._llm_tailor("r", "j", {}))
        self.assertEqual(self.calls, [])


class DemandCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init_db()
        market._demand_cache.clear()
        db.insert_job({
            "source": "t", "source_id": "a", "title": "Java Dev",
            "company": "Co", "location": "Houston, TX", "remote_flag": 0,
            "url": "", "description": "Java and Spring needed",
            "posted_at": "", "salary": "", "employment_type": ""})

    def tearDown(self):
        db.DB_PATH = self._old
        market._demand_cache.clear()
        self.tmp.cleanup()

    def test_second_call_within_ttl_is_cached(self):
        first = market.demand_map()
        self.assertEqual(first.get("java"), 1)
        db.insert_job({
            "source": "t", "source_id": "b", "title": "Python Dev",
            "company": "Co", "location": "Houston, TX", "remote_flag": 0,
            "url": "", "description": "Python and Django needed",
            "posted_at": "", "salary": "", "employment_type": ""})
        second = market.demand_map()
        self.assertEqual(second, first)  # still the cached snapshot
        market._demand_cache.clear()
        third = market.demand_map()
        self.assertEqual(third.get("python"), 1)


if __name__ == "__main__":
    unittest.main()
