"""Matches view resilience: the match list must load FIRST, and every
filter dropdown must fill independently. The old shape awaited
/api/consultants, then /api/sources/status, then /api/jobs/cities in
sequence before binding handlers or loading a single match — one
slow or failing call (a locked DB 500) took the whole view down and
the consultant filter simply never appeared. This guard fails if
that gating pattern comes back."""
import unittest
from pathlib import Path

APP_JS = (Path(__file__).resolve().parent.parent
          / "frontend" / "app.js").read_text()


def _render_matches_body() -> str:
    start = APP_JS.index("async function renderMatches")
    end = APP_JS.index("async function loadMatches", start)
    return APP_JS[start:end]


class MatchesViewResilienceTests(unittest.TestCase):
    def test_list_loads_before_any_dropdown_fill(self):
        body = _render_matches_body()
        # the list load is kicked off before any dropdown fill; since
        # the Nov 5 2026 fetch-once change it is loadMatches() (which
        # refetches only when the cached copy is empty or stale), not
        # a forced reload on every tab entry
        self.assertIn("loadMatches();", body)
        self.assertLess(body.index("loadMatches();"),
                        body.index('api("/api/consultants")'))

    def test_no_gating_awaits(self):
        body = _render_matches_body()
        for endpoint in ("/api/consultants", "/api/sources/status",
                         "/api/jobs/cities"):
            self.assertNotIn(f'await api("{endpoint}")', body,
                             f"{endpoint} must not gate the Matches view")

    def test_each_fill_has_its_own_catch(self):
        body = _render_matches_body()
        # one independent .catch per dropdown fill (consultants,
        # sources, cities) so a failure leaves the default option
        # and never blocks the page
        self.assertGreaterEqual(body.count(".catch(() => {})"), 3)


if __name__ == "__main__":
    unittest.main()
