"""Dice adapter — PERMANENTLY DISABLED.

Dice's public JSON endpoints (https://www.dice.com/api/jobs,
/api/jobs/search, /api/v2/jobs) all return 404 as of Oct 2026; there is no
supported public API. Shipping a scraper would break on bot checks, so the
adapter is intentionally disabled.

Dice coverage in v1: Adzuna aggregation + manual URL import
(Settings -> Jobs -> Import URL).
"""
NAME = "dice"
LABEL = "Dice (disabled — no public API)"


def enabled(settings: dict) -> bool:
    return False


def fetch(query: dict, settings: dict) -> list[dict]:
    raise RuntimeError("Dice adapter is disabled: no public JSON API (404 as of "
                       "Oct 2026). Use Adzuna or URL import instead.")
