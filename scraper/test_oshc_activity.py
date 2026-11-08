"""OSHC activity-system parser fixture tests. Run: python scraper/test_oshc_activity.py"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from parsers.oshc_activity import (
    extract_oshc_activity,
    build_activity_url_index,
    attach_activity_urls,
    parse_oshc_activity_html,
    _extract_times,
)
from fetch import clean, dedup_events, TODAY

FIX_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "oshc_activity")
SYN = os.path.join(FIX_DIR, "activitiesE_synthetic.html")
LIVE = os.path.join(FIX_DIR, "activitiesE.html")
IDX = os.path.join(FIX_DIR, "seminars_index_snippet.html")
BASE = "https://sms.oshc.hk/online/activitiesE.aspx"
SRC = {
    "name": "OSHC 職安局 研討會",
    "group": "OSHC",
    "region": "HK",
    "type": "H&S",
    "url": BASE,
}


def load_soup(path):
    with open(path, encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


def load_html(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_upcoming_accepted():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    gen = [e for e in raw if "Generative Artificial Intelligence" in e["title"]]
    assert gen, "upcoming GenAI seminar should be accepted"
    assert gen[0]["date"] == "2026-11-17"
    heat = [e for e in raw if "Heat Stress" in e["title"]]
    assert heat and heat[0]["date"] == "2026-12-22"
    print("upcoming accepted OK")


def test_past_rejected():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    # Parser may still emit past rows; clean() must reject them
    past_raw = [e for e in raw if "Historical" in e["title"] or e["date"] < TODAY.isoformat()]
    assert past_raw, "fixture should include a past activity"
    rejects = {}
    for e in past_raw:
        assert clean(e, SRC, rejects) is None
    assert rejects.get("date_range", 0) >= 1
    print("past rejected OK")


def test_free_activity():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    heat = next(e for e in raw if "Heat Stress" in e["title"])
    assert heat.get("is_free") is True
    print("free activity OK")


def test_paid_rejected():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    assert not any("HK$800" in e["title"] for e in raw)
    assert not any("Paid Training" in e["title"] for e in raw)
    print("paid rejected OK")


def test_date_parsing():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    mewp = next(e for e in raw if "Mobile Elevating" in e["title"])
    assert mewp["date"] == "2026-11-20"
    print("date parsing OK")


def test_time_parsing():
    assert _extract_times("((7:00-8:00 PM))") == ("19:00", "20:00")
    assert _extract_times("(3:30 p.m. – 4:45 p.m.)") == ("15:30", "16:45")
    assert _extract_times("(2:30 p.m. – 5:00 p.m.)") == ("14:30", "17:00")
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    gen = next(e for e in raw if "Generative" in e["title"])
    assert gen.get("start_time") == "19:00"
    assert gen.get("end_time") == "20:00"
    mewp = next(e for e in raw if "Mobile Elevating" in e["title"])
    assert mewp.get("start_time") == "14:30"
    assert mewp.get("end_time") == "17:00"
    print("time parsing OK")


def test_activity_title():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    assert any("Code of Practice on Safety Management" in e["title"] for e in raw)
    print("activity title OK")


def test_registration_deadline():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    heat = next(e for e in raw if "Heat Stress" in e["title"])
    assert heat.get("registration_deadline")
    assert "15 Dec" in heat["registration_deadline"]
    print("registration deadline OK")


def test_detail_registration_url():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    index = build_activity_url_index(load_html(IDX))
    enriched = attach_activity_urls(raw, index)
    gen = next(e for e in enriched if "Generative" in e["title"])
    assert "activityid=9905" in gen["url"]
    assert gen.get("registration_destination", "").endswith("activityid=9905")
    rejects = {}
    cleaned = clean(gen, SRC, rejects)
    assert cleaned is not None
    assert cleaned["registration"]["mechanism"] == "OSHC_PORTAL"
    assert "activityid=9905" in cleaned["registration"]["destination"]
    print("detail/registration URL OK")


def test_malformed_response():
    assert parse_oshc_activity_html("", BASE) == []
    assert parse_oshc_activity_html("<html><body>no table</body></html>", BASE) == []
    assert parse_oshc_activity_html("<<<not-html", BASE) == []
    print("malformed response OK")


def test_no_event_response():
    html = """<html><body><table id="GV_Activities">
    <tr><th></th><th>Date</th><th>Seminars &amp; Conferences</th><th>Venue</th></tr>
    </table></body></html>"""
    assert parse_oshc_activity_html(html, BASE) == []
    print("no-event response OK")


def test_parser_isolation():
    # Must not import / call Playwright, form post, or login helpers
    import parsers.oshc_activity as mod
    src = open(mod.__file__, encoding="utf-8").read()
    assert "playwright" not in src.lower()
    assert "__doPostBack" not in src or "never" in src.lower()  # may mention as comment
    assert "requests.post" not in src
    assert "login" not in src.lower() or "never" in src.lower()
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    assert isinstance(raw, list)
    print("parser isolation OK")


def test_duplicate_against_seminars_csb_labour():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    index = build_activity_url_index(load_html(IDX))
    enriched = attach_activity_urls(raw, index)
    gen = next(e for e in enriched if "Generative" in e["title"])
    rejects = {}
    act = clean(gen, SRC, rejects)
    assert act is not None
    seminars = {
        "id": "sem1",
        "name": act["name"],
        "org": "OSHC",
        "date": act["date"],
        "time": "",
        "hrs": None,
        "hrs_est": False,
        "type": "H&S",
        "disc": ["General"],
        "url": act["url"],
        "source": "OSHC Seminars & Conferences",
        "group": "OSHC",
    }
    csb = {
        "id": "csb1",
        "name": act["name"],
        "org": "OSHC",
        "date": act["date"],
        "time": act.get("time") or "",
        "hrs": act.get("hrs"),
        "hrs_est": act.get("hrs_est", False),
        "type": "H&S",
        "disc": ["General"],
        "url": "https://www.csb.gov.hk/english/oshcs/events/coming-events.html",
        "source": "公務員事務局 職安健活動 (勞工處/OSHC)",
        "group": "Labour Dept",
    }
    labour = {
        "id": "lab1",
        "name": act["name"],
        "org": "OSHC",
        "date": act["date"],
        "time": "",
        "hrs": None,
        "hrs_est": False,
        "type": "H&S",
        "disc": ["General"],
        "url": act["url"],
        "source": "勞工處 職業健康公開講座",
        "group": "Labour Dept",
    }
    # Same activity URL ⇒ strong_signal; frozen dedup keeps one
    result = dedup_events([act, seminars, csb, labour])
    assert len(result) == 1, f"expected 1 survivor, got {len(result)}"
    print("duplicate against Seminars/CSB/Labour OK")


def test_no_form_submission():
    src = open(
        os.path.join(os.path.dirname(__file__), "parsers", "oshc_activity.py"),
        encoding="utf-8",
    ).read()
    assert "requests.post" not in src
    assert "submit(" not in src.lower()
    assert "__dopostback" not in src.lower()
    assert "click enrol" not in src.lower()
    assert "enroll(" not in src.lower()
    print("no form submission OK")


def test_no_login_auth_bypass():
    src = open(
        os.path.join(os.path.dirname(__file__), "parsers", "oshc_activity.py"),
        encoding="utf-8",
    ).read()
    for banned in ("password", "captcha", "cookie", "authorization", "bypass"):
        assert banned not in src.lower()
    print("no login/auth bypass OK")


def test_social_rejected():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    assert not any("Dinner" in e["title"] for e in raw)
    print("social rejected OK")


def test_hs_classification():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    mewp = next(e for e in raw if "Mobile Elevating" in e["title"])
    assert mewp.get("type") == "H&S"
    print("H&S classification OK")


def test_live_fixture_parses():
    """Captured live listing still parses (structure guard)."""
    raw = extract_oshc_activity(load_soup(LIVE), BASE)
    assert len(raw) >= 1
    assert all(e.get("date") for e in raw)
    assert all(e.get("title") for e in raw)
    print(f"live fixture parses OK (n={len(raw)})")


def test_estimated_hours_via_clean():
    raw = extract_oshc_activity(load_soup(SYN), BASE)
    gen = next(e for e in raw if "Generative" in e["title"])
    rejects = {}
    c = clean(gen, SRC, rejects)
    assert c is not None
    assert c["hrs"] == 1.0
    assert c["hrs_est"] is True
    print("estimated hours via clean OK")


if __name__ == "__main__":
    test_upcoming_accepted()
    test_past_rejected()
    test_free_activity()
    test_paid_rejected()
    test_date_parsing()
    test_time_parsing()
    test_activity_title()
    test_registration_deadline()
    test_detail_registration_url()
    test_malformed_response()
    test_no_event_response()
    test_parser_isolation()
    test_duplicate_against_seminars_csb_labour()
    test_no_form_submission()
    test_no_login_auth_bypass()
    test_social_rejected()
    test_hs_classification()
    test_live_fixture_parses()
    test_estimated_hours_via_clean()
    print("All OSHC activity tests passed")
