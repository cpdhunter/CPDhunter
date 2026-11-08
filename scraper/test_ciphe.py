"""CIPHE Events Calendar parser fixture tests. Run: python scraper/test_ciphe.py"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from parsers.ciphe import extract_ciphe
from fetch import clean, dedup_events, TODAY

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "ciphe", "events_calendar.html")
BASE = "https://ciphe.org.hk/Events_Calendar.html"


def load():
    with open(FIX, encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


def test_future_technical_accepted():
    raw = extract_ciphe(load(), BASE)
    ami = [e for e in raw if "Advanced Metering" in e["title"]]
    assert ami, "AMI free seminar should be accepted"
    assert ami[0]["date"] == "2026-11-11"
    assert ami[0]["is_free"] is True
    print("future technical accepted OK")


def test_past_rejected_by_clean():
    raw = extract_ciphe(load(), BASE)
    src = {"name": "CIPHE Hong Kong Events", "group": "CIPHE", "region": "HK", "url": BASE}
    rejects = {}
    kept = [clean(e, src, rejects) for e in raw]
    kept = [k for k in kept if k]
    # Any past events in fixture must not survive clean()
    for k in kept:
        assert dt.date.fromisoformat(k["date"]) >= TODAY
    # Ensure date_range reject path works for an explicitly past raw event
    past = {
        "title": "Past CPD Seminar on Contract Law",
        "date": "2025-07-28",
        "url": BASE,
        "organizer": "CIPHE Hong Kong",
        "is_free": True,
    }
    assert clean(past, src, rejects) is None
    assert rejects.get("date_range", 0) >= 1
    print("past rejected OK")


def test_free_recognised():
    raw = extract_ciphe(load(), BASE)
    frees = [e for e in raw if e.get("is_free") is True]
    assert any("Advanced Metering" in e["title"] for e in frees)
    assert any("App Tasting" in e["title"] for e in frees)
    print("free recognised OK")


def test_paid_rejected():
    raw = extract_ciphe(load(), BASE)
    assert not any("BACnet" in e["title"] for e in raw)
    assert not any("BEAM Society" in e["title"] for e in raw) or all(
        e.get("is_free") is not False for e in raw if "BEAM" in e["title"]
    )
    # BACnet is paid HK$800 — must be absent
    assert not any("BACnet" in e["title"] for e in raw)
    print("paid rejected OK")


def test_fee_missing_null_where_allowed():
    raw = extract_ciphe(load(), BASE)
    water = [e for e in raw if "Smart Water" in e["title"]]
    assert water, "Smart Water (fee not stated) should be kept with free=null"
    assert water[0].get("is_free") is None
    print("fee missing null OK")


def test_dinner_social_rejected():
    raw = extract_ciphe(load(), BASE)
    assert not any("晚宴" in e["title"] or "Dinner" in e["title"] for e in raw)
    print("dinner/social rejected OK")


def test_news_rejected():
    raw = extract_ciphe(load(), BASE)
    assert not any("Create Your District" in e["title"] for e in raw)
    assert not any("Commemorative Booklet" in e["title"] for e in raw)
    print("news rejected OK")


def test_title_date_time():
    raw = extract_ciphe(load(), BASE)
    ami = next(e for e in raw if "Advanced Metering" in e["title"])
    assert "Application Procedures" in ami["title"]
    assert ami["date"] == "2026-11-11"
    assert ami.get("start_time") == "19:00"
    assert ami.get("end_time") == "21:30"
    print("title/date/time OK")


def test_cpd_hours_stated():
    raw = extract_ciphe(load(), BASE)
    ami = next(e for e in raw if "Advanced Metering" in e["title"])
    assert ami.get("cpd_hours") == 2
    print("CPD hours stated OK")


def test_registration_destination():
    raw = extract_ciphe(load(), BASE)
    ami = next(e for e in raw if "Advanced Metering" in e["title"])
    dest = ami.get("registration_destination") or ""
    assert "docs.google.com/forms" in dest or "forms.gle" in dest
    print("registration destination OK")


def test_registration_deadline():
    raw = extract_ciphe(load(), BASE)
    ami = next(e for e in raw if "Advanced Metering" in e["title"])
    assert ami.get("registration_deadline")
    assert "06 November 2026" in ami["registration_deadline"] or "November" in ami["registration_deadline"]
    print("registration deadline OK")


def test_malformed_html_resilience():
    soup = BeautifulSoup("<html><body><p>broken", "html.parser")
    assert extract_ciphe(soup, BASE) == []
    soup2 = BeautifulSoup("<html><body><article class='blog-item'><h3>NoDate Event Title Long Enough</h3><p>hello</p></article></body></html>", "html.parser")
    assert extract_ciphe(soup2, BASE) == []
    print("malformed HTML resilience OK")


def test_overseas_visit_rejected():
    raw = extract_ciphe(load(), BASE)
    assert not any("Dongguan" in e["title"] or "MiMEP" in e["title"] for e in raw)
    print("overseas visit rejected OK")


def test_duplicate_interaction():
    raw = extract_ciphe(load(), BASE)
    src = {"name": "CIPHE Hong Kong Events", "group": "CIPHE", "region": "HK", "url": BASE}
    rejects = {}
    events = []
    for e in raw:
        c = clean(e, src, rejects)
        if c:
            events.append(c)
    # Inject a near-duplicate from another org — must remain separate (different org)
    if events:
        twin = dict(events[0])
        twin["id"] = "a_dup_test"
        twin["org"] = "HKIE"
        twin["source"] = "HKIE Events"
        twin["url"] = "https://hkie.org.hk/events/other"
        before = len(events) + 1
        after = len(dedup_events(events + [twin]))
        assert after == before  # different org → no merge
    print("duplicate interaction OK")


def test_clean_pass_through_registration():
    raw = extract_ciphe(load(), BASE)
    ami = next(e for e in raw if "Advanced Metering" in e["title"])
    src = {"name": "CIPHE Hong Kong Events", "group": "CIPHE", "region": "HK", "url": BASE}
    c = clean(ami, src, {})
    assert c is not None
    assert c.get("free") is True
    assert c.get("hrs") == 2
    assert c.get("hrs_est") is False
    assert c.get("registration", {}).get("mechanism") == "GOOGLE_FORMS"
    assert "docs.google.com/forms" in (c["registration"].get("destination") or "")
    print("clean registration pass-through OK")


if __name__ == "__main__":
    test_future_technical_accepted()
    test_past_rejected_by_clean()
    test_free_recognised()
    test_paid_rejected()
    test_fee_missing_null_where_allowed()
    test_dinner_social_rejected()
    test_news_rejected()
    test_title_date_time()
    test_cpd_hours_stated()
    test_registration_destination()
    test_registration_deadline()
    test_malformed_html_resilience()
    test_overseas_visit_rejected()
    test_duplicate_interaction()
    test_clean_pass_through_registration()
    print("All CIPHE tests passed")
