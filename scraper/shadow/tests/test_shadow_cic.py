"""CIC shadow parser: real cards only; Event Types vocabulary is never a title."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRAPER = os.path.join(ROOT, "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

from title_quality import CIC_EVENT_TYPE_LABELS  # noqa: E402

from scraper.shadow.paths import CIC_URL, PRODUCTION_CIC, STATE_CIC  # noqa: E402
from scraper.shadow.scrapling_cic import parse_cic_html  # noqa: E402


def test_cic_titles_from_fixture():
    html = open(PRODUCTION_CIC, encoding="utf-8").read()
    result = parse_cic_html(html, CIC_URL, storage_file=STATE_CIC + ".test")
    events = result["events"]
    titles = [e["title"] for e in events]
    for label in CIC_EVENT_TYPE_LABELS:
        assert all(t.lower() != label.lower() for t in titles), titles
    assert "Job Fair" not in titles
    assert "Exhibition" not in titles
    assert "Festival" not in titles
    assert "Others" not in titles
    assert "Conference／Seminar" not in titles
    assert any(t == "Temporary Works Workshop 2026" for t in titles), titles
    assert result["candidate_count"] >= 1
    assert result["valid_title_count"] == len(events)
    workshop = next(e for e in events if "Temporary Works Workshop 2026" in e["title"])
    assert workshop["date"] == "2026-11-20", workshop
    assert "cic.hk" in (workshop["url"] or "") and "temporary-works-workshop-2026" in (workshop["url"] or "")
    print("test_cic_titles_from_fixture OK", titles)


if __name__ == "__main__":
    test_cic_titles_from_fixture()
    print("CIC shadow tests passed")
