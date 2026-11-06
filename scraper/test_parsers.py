"""Minimal parser smoke tests + dedup tests. Run: python scraper/test_parsers.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from fetch import parse_date, classify_rule, dedup_events

def test_parse_date():
    assert parse_date("9-11 Dec 2026") == "2026-12-09"
    assert parse_date("06.11.2026") == "2026-11-06"
    assert parse_date("09 November 2026") == "2026-11-09"
    assert parse_date("4 Dec, 2026") == "2026-12-04"
    print("parse_date OK")

def test_classify():
    assert classify_rule("Safety at height seminar") == "H&S"
    assert classify_rule("NEC contract workshop") == "GPM"
    assert classify_rule("Structural analysis lecture") == "Technical"
    print("classify_rule OK")

def test_dedup_oshc_csb():
    oshc = {
        "name": "【Heart Caring Campaign/Joyful@Healthy Workplace】High Stress Actually “Breaks Your Heart”? The Relationship Between Mental Health and Cardiovascular Disease Webinar",
        "org": "OSHC",
        "date": "2026-11-06",
        "source": "OSHC Seminars & Conferences",
        "url": "https://www.oshc.org.hk/eng/main/training/seminars_conferences/",
        "hrs": None,
        "hrs_est": False,
    }
    csb = {
        "name": "【Heart Caring Campaign/Joyful@Healthy Workplace】Does High Stress “Break Your Heart”? The Relationship Between Mental Health and Cardiovascular Disease Webinar",
        "org": "OSHC",
        "date": "2026-11-06",
        "source": "公務員事務局 職安健活動 (勞工處/OSHC)",
        "url": "https://www.csb.gov.hk/english/oshcs/events/coming-events.html",
        "hrs": None,
        "hrs_est": False,
    }
    result = dedup_events([oshc, csb])
    assert len(result) == 1, f"expected 1, got {len(result)}"
    assert "OSHC Seminars" in result[0]["source"]
    print("dedup OSHC/CSB OK -> 1 survivor OSHC Seminars")

def test_dedup_nec_separate():
    a = {"name": "NEC4 ECC Contract Administration Workshop — Compensation Events", "org": "HKIE", "date": "2026-12-01", "source": "HKIE", "url": "https://hkie.org.hk/a", "hrs": None, "hrs_est": False}
    b = {"name": "NEC4 ECC Contract Administration Workshop — Early Warning Notices", "org": "HKIE", "date": "2026-12-01", "source": "HKIE", "url": "https://hkie.org.hk/b", "hrs": None, "hrs_est": False}
    result = dedup_events([a, b])
    assert len(result) == 2
    print("dedup NEC separate OK")

def test_dedup_tw_separate():
    a = {"name": "Temporary Works Safety Seminar — Design and Management", "org": "CIC", "date": "2026-12-01", "source": "CIC", "url": "https://cic.hk/a", "hrs": None, "hrs_est": False}
    b = {"name": "Temporary Works Safety Seminar — Inspection and Monitoring", "org": "CIC", "date": "2026-12-01", "source": "CIC", "url": "https://cic.hk/b", "hrs": None, "hrs_est": False}
    result = dedup_events([a, b])
    assert len(result) == 2
    print("dedup Temporary Works separate OK")

def test_dedup_high_sim_no_signal():
    a = {"name": "Advanced Structural Analysis Techniques for High-Rise Buildings Workshop", "org": "HKIE", "date": "2026-12-01", "source": "HKIE", "url": "https://hkie.org.hk/list", "hrs": None, "hrs_est": False}
    b = {"name": "Advanced Structural Analysis Techniques for High-Rise Buildings Seminar", "org": "HKIE", "date": "2026-12-01", "source": "HKIE", "url": "https://hkie.org.hk/list", "hrs": None, "hrs_est": False}
    result = dedup_events([a, b])
    assert len(result) == 2
    print("dedup high sim no strong signal remains separate OK")

def test_dedup_listing_url_alone():
    a = {"name": "Some Unique Event Title One", "org": "OSHC", "date": "2026-12-01", "source": "OSHC", "url": "https://www.oshc.org.hk/list", "hrs": None, "hrs_est": False}
    b = {"name": "Some Unique Event Title Two", "org": "OSHC", "date": "2026-12-01", "source": "CSB", "url": "https://www.oshc.org.hk/list", "hrs": None, "hrs_est": False}
    result = dedup_events([a, b])
    assert len(result) == 2
    print("dedup listing URL alone remains separate OK")

def test_dedup_different_org():
    a = {"name": "Identical Title Event", "org": "HKIE", "date": "2026-12-01", "source": "HKIE", "url": "https://a", "hrs": None, "hrs_est": False}
    b = {"name": "Identical Title Event", "org": "CIC", "date": "2026-12-01", "source": "CIC", "url": "https://b", "hrs": None, "hrs_est": False}
    result = dedup_events([a, b])
    assert len(result) == 2
    print("dedup different organizer remains separate OK")

if __name__ == "__main__":
    test_parse_date()
    test_classify()
    test_dedup_oshc_csb()
    test_dedup_nec_separate()
    test_dedup_tw_separate()
    test_dedup_high_sim_no_signal()
    test_dedup_listing_url_alone()
    test_dedup_different_org()
    print("All tests passed")
