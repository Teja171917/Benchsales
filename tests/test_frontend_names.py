"""Guard against JS function-name collisions in frontend/app.js: the
view builders (renderMatches, renderJobs, ...) must each be defined
exactly once — a second definition silently overrides the first in
the browser and can blank a whole view (the Nov 2026 Matches outage:
a new card renderer reused the view builder's name)."""
import re
import unittest
from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "frontend" / "app.js"


class FrontendNameTests(unittest.TestCase):
    def test_no_duplicate_function_definitions(self):
        src = APP_JS.read_text()
        names = re.findall(r"^function (\w+)\(", src, re.M)
        dupes = {n for n in names if names.count(n) > 1}
        self.assertEqual(dupes, set(), f"duplicate definitions: {dupes}")

    def test_matches_view_fills_its_own_city_dropdown(self):
        src = APP_JS.read_text()
        view = src.split("async function renderMatches(")[1].split(
            "async function loadMatches(")[0]
        self.assertIn('api("/api/jobs/cities")', view)
        self.assertIn('$("#mt-city").innerHTML', view)

    def test_matches_view_and_cards_are_distinct(self):
        src = APP_JS.read_text()
        self.assertEqual(len(re.findall(r"function renderMatches\(", src)), 1)
        self.assertEqual(len(re.findall(r"function renderMatchCards\(", src)), 1)
        self.assertIn("renderMatchCards();", src)


if __name__ == "__main__":
    unittest.main()
