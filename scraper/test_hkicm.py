"""HKICM Learning/CPD parser fixture tests. Run: python scraper/test_hkicm.py"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from parsers.hkicm import extract_hkicm
from fetch import clean, dedup_events, TODAY

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hkicm", "learning_cpd.html")
NEWS = os.path.join(os.path.dirname(__file__), "fixtures", "hkicm", "news_and_dinner.html")
BASE = "https://hkicm.org.hk/learning-cpd/"


def load(path=FIX):
    with open(path, encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


def test_cpd_event_accepted():
    raw = extract_hkicm(load(), BASE)
    mic = [e for e in raw if "MiC Solutions" in e["title"] or "KTN 24" in e["title"]]
    assert mic, "free MiC technical seminar should be accepted"
    assert mic[0]["is_free"] is True
    assert mic[0]["date"] == "2026-12-16"
    assert "hkicm.org.hk/event/" in mic[0]["url"]
    print("CPD event accepted OK")


def test_past_rejected():
    raw = extract_hkicm(load(), BASE)
    # Past Events wrapper must not be scraped into upcoming results with past dates surviving
    src = {"name": "HKICM Learning / CPD", "group": "HKICM", "region": "HK", "url": BASE}
    rejects = {}
    kept = [clean(e, src, rejects) for e in raw]
    kept = [k for k in kept if k]
    for k in kept:
        assert dt.date.fromisoformat(k["date"]) >= TODAY
    past = {
        "title": "Lessons Learnt from Recent Fire Incidents",
        "date": "2026-11-06",
        "url": "https://hkicm.org.hk/event/cpd20261106s/",
        "organizer": "HKICM",
        "is_free": True,
    }
    # 6 Nov 2026 is before TODAY (8 Nov 2026) → reject
    assert clean(past, src, rejects) is None
    print("past rejected OK")


def test_free_recognised():
    raw = extract_hkicm(load(), BASE)
    frees = [e for e in raw if e.get("is_free") is True]
    assert any("MiC" in e["title"] or "KTN" in e["title"] for e in frees)
    assert any("Aviation Safety" in e["title"] or "Tower to Sky" in e["title"] for e in frees)
    print("free recognised OK")


def test_paid_rejected():
    raw = extract_hkicm(load(), BASE)
    assert not any("Excavation and Lateral Support" in e["title"] for e in raw)
    assert not any("Waterproofing" in e["title"] for e in raw)
    assert not any("Buildings Ordinance" in e["title"] for e in raw)
    print("paid rejected OK")


def test_fee_missing_null_where_allowed():
    # Synthetic card without fee
    html = '''<!DOCTYPE html><html><body><div class="events-wrapper events-open">
    <table><tr class="item-event item-learning-cpd"><td>
    <div class="event-title"><a href="https://hkicm.org.hk/event/cpd20261220s/">Technical Seminar on Smart Site Logistics</a></div>
    <div class="event-metas"><div class="left">20 Dec</div><div>7:00 pm – 8:30 pm</div></div>
    </td></tr></table></div></body></html>'''
    raw = extract_hkicm(BeautifulSoup(html, "html.parser"), BASE)
    assert len(raw) == 1
    assert raw[0]["is_free"] is None
    assert raw[0]["date"] == "2026-12-20"
    print("fee missing null OK")


def test_dinner_social_rejected():
    raw = extract_hkicm(load(NEWS), BASE)
    assert not any("Dinner" in e["title"] for e in raw)
    print("dinner/social rejected OK")


def test_news_rejected():
    raw = extract_hkicm(load(NEWS), BASE)
    assert not any("Media Interview" in e["title"] for e in raw)
    print("news rejected OK")


def test_membership_session_rejected():
    raw = extract_hkicm(load(), BASE)
    assert not any("HOW TO BECOME" in e["title"].upper() for e in raw)
    print("membership session rejected OK")


def test_title_date_time():
    raw = extract_hkicm(load(), BASE)
    mic = next(e for e in raw if "KTN 24" in e["title"] or "MiC" in e["title"])
    assert mic["date"] == "2026-12-16"
    assert mic.get("start_time") == "18:30"
    assert mic.get("end_time") == "20:00"
    print("title/date/time OK")


def test_cpd_hours_from_duration_via_clean():
    raw = extract_hkicm(load(), BASE)
    mic = next(e for e in raw if "KTN 24" in e["title"] or "MiC" in e["title"])
    src = {"name": "HKICM Learning / CPD", "group": "HKICM", "region": "HK", "url": BASE}
    c = clean(mic, src, {})
    assert c is not None
    # 18:30-20:00 = 1.5h estimated
    assert c["hrs"] == 1.5
    assert c["hrs_est"] is True
    print("CPD hours estimated from time OK")


def test_registration_destination_detail_url():
    raw = extract_hkicm(load(), BASE)
    mic = next(e for e in raw if "KTN 24" in e["title"] or "MiC" in e["title"])
    assert mic["url"].startswith("https://hkicm.org.hk/event/")
    print("detail URL as event url OK")


def test_malformed_html_resilience():
    assert extract_hkicm(BeautifulSoup("<html><body>", "html.parser"), BASE) == []
    print("malformed HTML resilience OK")


def test_safety_classification():
    raw = extract_hkicm(load(), BASE)
    safety = [e for e in raw if "Aviation Safety" in e["title"] or "Tower to Sky" in e["title"]]
    assert safety
    assert safety[0]["type"] == "H&S"
    print("safety classification OK")


def test_duplicate_interaction():
    raw = extract_hkicm(load(), BASE)
    src = {"name": "HKICM Learning / CPD", "group": "HKICM", "region": "HK", "url": BASE}
    events = [clean(e, src, {}) for e in raw]
    events = [e for e in events if e]
    if events:
        twin = dict(events[0])
        twin["id"] = "a_hkicm_dup"
        twin["org"] = "CIC"
        twin["source"] = "CIC 建造業議會 Events"
        twin["url"] = "https://www.cic.hk/en/events/other"
        assert len(dedup_events(events + [twin])) == len(events) + 1
    print("duplicate interaction OK")


if __name__ == "__main__":
    test_cpd_event_accepted()
    test_past_rejected()
    test_free_recognised()
    test_paid_rejected()
    test_fee_missing_null_where_allowed()
    test_dinner_social_rejected()
    test_news_rejected()
    test_membership_session_rejected()
    test_title_date_time()
    test_cpd_hours_from_duration_via_clean()
    test_registration_destination_detail_url()
    test_malformed_html_resilience()
    test_safety_classification()
    test_duplicate_interaction()
    print("All HKICM tests passed")
