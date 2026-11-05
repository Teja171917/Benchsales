"""US filter tightening + stored-pool sweep (Nov 5 2026).

Teja kept seeing European jobs ("like from arbeitnow") after the
boards were unwired. Two holes: (1) the location filter's blocklist
named Berlin/London but not the bare foreign cities actually in the
pool (Munich, Zürich, Utrecht...), so a posting naming only the city
fell through as "unknown — keep"; (2) nothing ever re-checked STORED
jobs — Arbeitnow-era rows sat in every workspace and kept matching.

The sweep (db.purge_non_us_jobs, run per workspace in the collector's
prepare phase) deletes stored jobs failing the filter, plus every job
from a retired board whatever its location says.
"""
import tempfile
import unittest
from pathlib import Path

from app import db
from app.usa import is_us_job


class TightenedFilterTests(unittest.TestCase):
    def test_bare_foreign_cities_now_dropped(self):
        for loc in ("Munich", "München", "Hamburg", "Cologne", "Zürich",
                    "Nyon", "Utrecht", "Eindhoven", "Bern", "Vienna",
                    "Manchester", "Edinburgh", "Aachen",
                    "Aachen, North Rhine-Westphalia", "Milton Keynes",
                    "Den Haag", "Homeoffice", "Medellin"):
            assert not is_us_job({"location": loc}), loc

    def test_us_namesakes_with_state_marker_stay(self):
        # has_us_marker runs before the blocklist: a US state in the
        # string keeps the job even when the city name is European
        for loc in ("Manchester, NH", "Vienna, VA", "Bern, KS",
                    "Cambridge, MA", "Bristol, TN", "New York, NY",
                    "Houston, TX"):
            assert is_us_job({"location": loc}), loc

    def test_unknown_and_remote_still_kept(self):
        for loc in ("", "Remote", "Remote job", "US",
                    "Schiller Park, Cook County"):
            assert is_us_job({"location": loc}), loc


class PurgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        self.consultant = db.create_consultant({"name": "Purge Tester"})

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def _job(self, source, location, sid):
        return db.insert_job({"source": source, "source_id": sid,
                              "title": "Java Developer", "company": "Acme",
                              "location": location, "description": "x",
                              "url": ""})

    def test_purge_removes_non_us_and_dead_sources_only(self):
        us = self._job("dice", "Houston, TX", "p1")
        eu = self._job("phenom", "Munich", "p2")
        dead = self._job("arbeitnow", "Remote job", "p3")
        dead_eu = self._job("remoteok", "Berlin", "p4")
        for jid in (us, eu, dead, dead_eu):
            db.insert_match(self.consultant["id"], jid, 90, {}, [])
        result = db.purge_non_us_jobs()
        assert result == {"jobs": 3, "matches": 3}, result
        with db.get_conn() as conn:
            left = [r["id"] for r in conn.execute("SELECT id FROM jobs")]
            matches_left = conn.execute(
                "SELECT COUNT(*) FROM matches").fetchone()[0]
        assert left == [us]
        assert matches_left == 1

    def test_purge_is_idempotent(self):
        self._job("adzuna", "Zürich", "q1")
        assert db.purge_non_us_jobs() == {"jobs": 1, "matches": 0}
        assert db.purge_non_us_jobs() == {"jobs": 0, "matches": 0}


if __name__ == "__main__":
    unittest.main()
