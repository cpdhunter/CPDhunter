"""HKIE Events complete official eventlist discovery tests.

Run: python scraper/test_hkie_eventlist.py
"""
import datetime as dt
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from fetch import KEEP_DAYS_AHEAD, clean, dedup_events, generic_extract
from parsers.hkie_event_detail import enrich_hkie_events, parse_hkie_event_detail
from parsers.hkie_eventlist import (
    MAX_WINDOWS,
    OFFICIAL_WINDOW_DAYS,
    discover_hkie_events,
    format_daterange,
    is_hkie_events_listing_url,
    iter_hkie_date_windows,
    parse_hkie_eventlist_item,
    parse_hkie_eventlist_payload,
)
from title_quality import title_quality_reason

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hkie_eventlist")
DETAIL_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "hkie_event_detail")
FRC_URL = "https://hkie.org.hk/events/event-detail/6af419991f1d426669c456b1/"
FRC_TITLE = "Technical Seminar: Infrastructure Construction using Fibre Reinforced Concrete"
FRC_ID = "6af419991f1d426669c456b1"
BRIDGE_ID = "6ad88a0e5f713be01511b1b6"
BIM_ID = "6af41c5c1f1d426669c45827"
SRC = {
    "name": "HKIE Events",
    "group": "HKIE",
    "region": "HK",
    "url": "https://hkie.org.hk/events/",
}
TODAY_FX = dt.date(2026, 11, 16)


def _recorded_windows():
    with open(os.path.join(FIX, "eventlist_windows.json"), encoding="utf-8") as f:
        return json.load(f)["windows"]


def _payload_map():
    return {w["daterange"]: {"result": w.get("result"), "data": w.get("data"), "msg": w.get("msg")} for w in _recorded_windows()}


def _fetch_recorded(daterange, payloads=None):
    payloads = payloads if payloads is not None else _payload_map()
    if daterange not in payloads:
        return {"result": 0, "data": [], "msg": "Select Successful"}
    return payloads[daterange]


def _item(**kw):
    base = {
        "id": "aaaaaaaaaaaaaaaaaaaaaaaa",
        "title": "Sample Technical Seminar",
        "date": "16 November 2026",
        "date_from": "2026-11-16",
        "date_to": "2026-11-16",
        "group_name": "Civil Division",
        "type_name": "",
    }
    base.update(kw)
    return base


def test_listing_url_scope():
    assert is_hkie_events_listing_url("https://hkie.org.hk/events/")
    assert is_hkie_events_listing_url("https://hkie.org.hk/events")
    assert is_hkie_events_listing_url("https://www.hkie.org.hk/tc/events/")
    assert not is_hkie_events_listing_url(
        "https://hkie.org.hk/professional-development/continuing-professional-development/cpd-calendar/"
    )
    assert not is_hkie_events_listing_url("https://hkie.org.hk/events/event-detail/6af419991f1d426669c456b1/")
    assert not is_hkie_events_listing_url("https://bd.hkie.org.hk/category/events-activities/")
    assert not is_hkie_events_listing_url("https://www.hkie-st.org/events-and-activities/")
    assert not is_hkie_events_listing_url("https://www.cic.hk/en/events")
    print("listing URL scope OK")


def test_windows_cover_today_to_horizon():
    assert KEEP_DAYS_AHEAD == 180
    assert OFFICIAL_WINDOW_DAYS == 30
    windows = iter_hkie_date_windows(TODAY_FX, horizon_days=KEEP_DAYS_AHEAD, window_days=30)
    assert windows[0][0] == TODAY_FX
    assert windows[-1][1] == TODAY_FX + dt.timedelta(days=180)
    # Adjacent windows share the boundary day.
    for prev, nxt in zip(windows, windows[1:]):
        assert nxt[0] == prev[1]
        span = (prev[1] - prev[0]).days
        assert span <= 30
    covered = set()
    for start, end in windows:
        d = start
        while d <= end:
            covered.add(d)
            d += dt.timedelta(days=1)
    expect = {TODAY_FX + dt.timedelta(days=i) for i in range(181)}
    assert covered == expect
    assert len(windows) <= MAX_WINDOWS
    print(f"windows cover TODAY..TODAY+180 ({len(windows)} windows) OK")


def test_discovery_not_capped_at_20():
    items = [
        _item(
            id=f"{i:024x}",
            title=f"Technical Seminar Number {i:02d} on Infrastructure",
            date_from=(TODAY_FX + dt.timedelta(days=i)).isoformat(),
            date_to=(TODAY_FX + dt.timedelta(days=i)).isoformat(),
            date=(TODAY_FX + dt.timedelta(days=i)).strftime("%d %B %Y"),
        )
        for i in range(25)
    ]

    def fetch(daterange):
        return {"result": 0, "data": items}

    events, stats = discover_hkie_events(
        fetch,
        today=TODAY_FX,
        horizon_days=180,
        max_windows=1,
    )
    assert len(events) == 25, f"hard cap still applied: {len(events)}"
    assert stats["unique_events"] == 25
    print("discovery not capped at 20 OK")


def test_recorded_feed_includes_bridge_and_5d_bim():
    events, stats = discover_hkie_events(
        _fetch_recorded,
        today=TODAY_FX,
        horizon_days=180,
        window_days=30,
    )
    assert len(events) > 20
    by_id = {e["official_id"]: e for e in events}
    assert BRIDGE_ID in by_id
    bridge = by_id[BRIDGE_ID]
    assert "Innovative Movable Bridge Design in Hong Kong" in bridge["title"]
    assert bridge["date"] == "2026-12-02"
    assert bridge["url"] == f"https://hkie.org.hk/events/event-detail/{BRIDGE_ID}/"
    assert bridge["division"] == "Civil Division"
    assert bridge["organizer"] == "Civil Division"
    assert BIM_ID in by_id
    bim = by_id[BIM_ID]
    assert "5D BIM" in bim["title"]
    assert bim["date"] == "2026-12-18"
    assert bim["division"] == "Civil Division"
    assert bim["url"] == f"https://hkie.org.hk/events/event-detail/{BIM_ID}/"
    assert stats["stopped"] in ("horizon", None) or stats["windows_fetched"] >= 6
    # 5D BIM is outside the official default 30-day picker (today+30 = 2026-12-16).
    first = format_daterange(TODAY_FX, TODAY_FX + dt.timedelta(days=30))
    first_ids = {r["official_id"] for r in parse_hkie_eventlist_payload(_fetch_recorded(first))}
    assert BRIDGE_ID in first_ids
    assert BIM_ID not in first_ids
    print(f"recorded feed Movable Bridge + 5D BIM OK (unique={len(events)})")


def test_discovery_record_fields():
    rec = parse_hkie_eventlist_item(
        {
            "id": FRC_ID,
            "title": "  " + FRC_TITLE + " ",
            "date": "26 November 2026",
            "date_from": "2026-11-26",
            "date_to": "2026-11-26",
            "group_name": "Civil Division",
            "type_name": "",
        }
    )
    assert rec["official_id"] == FRC_ID
    assert rec["title"] == FRC_TITLE
    assert rec["date"] == "2026-11-26"
    assert rec["date_from"] == "2026-11-26"
    assert rec["url"] == FRC_URL
    assert rec["organizer"] == "Civil Division"
    assert rec["division"] == "Civil Division"
    assert title_quality_reason(rec["title"]) is None
    print("discovery record fields OK")


def test_enrichment_applied_after_discovery():
    events, _stats = discover_hkie_events(
        _fetch_recorded,
        today=TODAY_FX,
        horizon_days=180,
    )
    frc = next(e for e in events if e["official_id"] == FRC_ID)
    # Listing payload has no time / mode — enrichment supplies them.
    assert not frc.get("time")
    assert not frc.get("mode")
    with open(os.path.join(DETAIL_FIX, "frc_civil_hybrid.html"), encoding="utf-8") as f:
        html = f.read()

    def fetch_detail(url):
        assert url == FRC_URL
        return {"title": FRC_TITLE, "html": html}

    raw, stats = enrich_hkie_events([frc], fetch_detail, today="2026-11-16")
    assert stats["enriched"] == 1
    assert len(raw) == 1
    assert raw[0]["start_time"] == "19:00"
    assert raw[0]["end_time"] == "20:00"
    assert raw[0]["mode"] == "HYBRID"
    assert "Civil" in raw[0]["disciplines"]
    rejects = {}
    cleaned = clean(raw[0], SRC, rejects)
    assert cleaned, rejects
    assert cleaned["name"] == FRC_TITLE
    assert cleaned["date"] == "2026-11-26"
    assert cleaned["time"] == "19:00-20:00"
    assert cleaned["mode"] == "HYBRID"
    assert "Civil" in cleaned["disc"]
    assert cleaned["hrs"] == 1.0
    assert cleaned["hrs_est"] is True
    # Discovery module must not reimplement detail parsing.
    import parsers.hkie_eventlist as el

    src = inspect.getsource(el)
    assert "parse_hkie_event_detail" not in src
    assert "Hybrid with Webinar" not in src
    print("enrichment applied after discovery OK")


def test_no_listing_detail_duplicate():
    events, _ = discover_hkie_events(
        _fetch_recorded,
        today=TODAY_FX,
        horizon_days=180,
    )
    urls = [e["url"] for e in events]
    ids = [e["official_id"] for e in events]
    assert len(urls) == len(set(urls))
    assert len(ids) == len(set(ids))
    assert all("/events/event-detail/" in u for u in urls)
    assert all(u.rstrip("/").endswith(i) for u, i in zip(urls, ids))
    # Discovery itself only emits one detail-URL record per official id.
    # Cleaning the same discovered row twice still dedups. Frozen dedup
    # thresholds are not changed here.
    frc = next(e for e in events if e["official_id"] == FRC_ID)
    with open(os.path.join(DETAIL_FIX, "frc_civil_hybrid.html"), encoding="utf-8") as f:
        html = f.read()
    raw, _ = enrich_hkie_events(
        [dict(frc)],
        lambda url: {"title": FRC_TITLE, "html": html},
        today="2026-11-16",
    )
    a = clean(raw[0], SRC, {})
    b = clean(dict(raw[0]), SRC, {})
    merged = dedup_events([a, b])
    assert a["id"] == b["id"]
    assert len(merged) == 1
    print("no listing+detail duplicate OK")


def test_safety_duplicate_page_stops():
    calls = []

    def fetch(daterange):
        calls.append(daterange)
        return {"result": 0, "data": [_item(id="sameid000000000000000001", title="Repeated Event Title Here")]}

    events, stats = discover_hkie_events(
        fetch,
        today=TODAY_FX,
        horizon_days=180,
        window_days=30,
        max_windows=16,
    )
    assert len(events) == 1
    assert stats["stopped"] == "duplicate_page"
    assert len(calls) == 2  # first page accepted, second identical page stops
    print("duplicate page stop OK")


def test_safety_empty_window_does_not_skip_later_horizon():
    """Official feed can have mid-range gaps; empty must not abort later windows."""
    late_day = TODAY_FX + dt.timedelta(days=90)
    late = _item(
        id="lateevent0000000000000001",
        title="Later Civil Division Technical Seminar",
        date_from=late_day.isoformat(),
        date_to=late_day.isoformat(),
    )

    def fetch(daterange):
        start = dt.datetime.strptime(daterange.split(" - ")[0], "%d/%m/%Y").date()
        end = dt.datetime.strptime(daterange.split(" - ")[1], "%d/%m/%Y").date()
        if start <= late_day <= end:
            return {"result": 0, "data": [late]}
        return {"result": 0, "data": []}

    events, stats = discover_hkie_events(
        fetch,
        today=TODAY_FX,
        horizon_days=180,
        window_days=30,
    )
    assert stats["empty_windows"] >= 1
    assert len(events) == 1
    assert events[0]["official_id"] == "lateevent0000000000000001"
    assert stats["stopped"] == "horizon"
    print("empty mid-horizon window continues OK")


def test_safety_max_windows_stops():
    calls = []

    def fetch(daterange):
        calls.append(daterange)
        i = len(calls)
        return {
            "result": 0,
            "data": [
                _item(
                    id=f"{i:024x}",
                    title=f"Window {i} Technical Seminar on Bridges",
                    date_from=(TODAY_FX + dt.timedelta(days=i)).isoformat(),
                    date_to=(TODAY_FX + dt.timedelta(days=i)).isoformat(),
                )
            ],
        }

    events, stats = discover_hkie_events(
        fetch,
        today=TODAY_FX,
        horizon_days=180,
        window_days=30,
        max_windows=2,
    )
    assert len(calls) == 2
    assert len(events) == 2
    assert stats["stopped"] == "max_windows"
    print("max windows stop OK")


def test_safety_repeated_ids_across_overlap_still_unique():
    """Boundary-day overlap repeats an id; the event is stored once."""
    edge = TODAY_FX + dt.timedelta(days=30)
    ev = _item(
        id="edgeevent0000000000000001",
        title="Boundary Day Civil Seminar",
        date_from=edge.isoformat(),
        date_to=edge.isoformat(),
    )

    def fetch(daterange):
        start = dt.datetime.strptime(daterange.split(" - ")[0], "%d/%m/%Y").date()
        end = dt.datetime.strptime(daterange.split(" - ")[1], "%d/%m/%Y").date()
        if start <= edge <= end:
            return {"result": 0, "data": [ev]}
        return {"result": 0, "data": []}

    events, _stats = discover_hkie_events(
        fetch,
        today=TODAY_FX,
        horizon_days=60,
        window_days=30,
    )
    assert len(events) == 1
    print("overlapped official id stored once OK")


def test_generic_extract_still_capped_for_other_sources():
    from bs4 import BeautifulSoup

    lis = []
    for i in range(25):
        d = (TODAY_FX + dt.timedelta(days=i)).strftime("%d %B %Y")
        lis.append(
            f'<li><a href="/events/item-{i}">Technical Briefing Number {i:02d} on Policy {d}</a></li>'
        )
    soup = BeautifulSoup("<html><body><ul>" + "".join(lis) + "</ul></body></html>", "html.parser")
    raw = generic_extract(soup, "https://www.cic.org.uk/events")
    assert len(raw) == 20, f"generic_extract cap changed: {len(raw)}"
    print("generic_extract still capped at 20 for other sources OK")


def test_process_source_routes_hkie_events_to_eventlist():
    import fetch as fetch_mod

    recorded = []
    fixture_events, _ = discover_hkie_events(_fetch_recorded, today=TODAY_FX, horizon_days=180)

    def fake_discover(*a, **k):
        recorded.append("eventlist")
        return fixture_events, {"unique_events": len(fixture_events), "stopped": "horizon"}

    def fake_generic(*a, **k):
        recorded.append("generic")
        return [{"title": "SHOULD NOT USE GENERIC EXTRACTOR", "date": "2026-12-02", "url": "https://example.com/x"}]

    def fake_fetch_html(url, use_playwright=False, session=None):
        return "<html><head><title>Events - HKIE</title></head><body></body></html>"

    orig_fetch = fetch_mod.fetch_html
    orig_generic = fetch_mod.generic_extract
    orig_pw = fetch_mod.PLAYWRIGHT_OK
    fetch_mod.fetch_html = fake_fetch_html
    fetch_mod.generic_extract = fake_generic
    fetch_mod.PLAYWRIGHT_OK = False
    import parsers.hkie_eventlist as el
    import parsers.hkie_event_detail as detail

    orig_disc = el.discover_hkie_events_from_api
    orig_enrich = detail.enrich_hkie_events_from_api
    el.discover_hkie_events_from_api = fake_discover

    def fake_enrich(events, **kw):
        recorded.append("enrich")
        return events, {"enriched": 1, "fetched": 0}

    detail.enrich_hkie_events_from_api = fake_enrich
    try:
        raw, method, title = fetch_mod.process_source(SRC)
    finally:
        fetch_mod.fetch_html = orig_fetch
        fetch_mod.generic_extract = orig_generic
        fetch_mod.PLAYWRIGHT_OK = orig_pw
        el.discover_hkie_events_from_api = orig_disc
        detail.enrich_hkie_events_from_api = orig_enrich
    assert method == "hkie-eventlist+detail"
    assert recorded == ["eventlist", "enrich"]
    assert len(raw) == len(fixture_events)
    assert any(e.get("official_id") == BRIDGE_ID for e in raw)
    assert title == "Events - HKIE"
    print(f"process_source routes HKIE Events to eventlist ({method}) OK")


def test_process_source_does_not_steal_other_sources():
    import fetch as fetch_mod

    called = []

    def fake_discover(*a, **k):
        called.append("eventlist")
        raise AssertionError("HKIE eventlist must not run for CIC")

    def fake_fetch_html(url, use_playwright=False, session=None):
        return "<html><head><title>CIC Events</title></head><body></body></html>"

    orig_fetch = fetch_mod.fetch_html
    orig_pw = fetch_mod.PLAYWRIGHT_OK
    orig_cic = fetch_mod.extract_cic
    fetch_mod.fetch_html = fake_fetch_html
    fetch_mod.PLAYWRIGHT_OK = False

    def fake_cic(soup, url):
        called.append("cic")
        return [{"title": "CIC Technical Seminar on Safety", "date": "2026-12-01", "url": "https://www.cic.hk/en/events/x"}]

    fetch_mod.extract_cic = fake_cic
    import parsers.hkie_eventlist as el

    orig_disc = el.discover_hkie_events_from_api
    el.discover_hkie_events_from_api = fake_discover
    try:
        raw, method, title = fetch_mod.process_source(
            {"name": "CIC 建造業議會 Events", "url": "https://www.cic.hk/en/events", "region": "HK"}
        )
    finally:
        fetch_mod.fetch_html = orig_fetch
        fetch_mod.PLAYWRIGHT_OK = orig_pw
        fetch_mod.extract_cic = orig_cic
        el.discover_hkie_events_from_api = orig_disc
    assert "eventlist" not in called
    assert called == ["cic"]
    assert method == "cic-list"
    assert len(raw) == 1
    print("other sources still use existing extractors OK")


if __name__ == "__main__":
    test_listing_url_scope()
    test_windows_cover_today_to_horizon()
    test_discovery_not_capped_at_20()
    test_recorded_feed_includes_bridge_and_5d_bim()
    test_discovery_record_fields()
    test_enrichment_applied_after_discovery()
    test_no_listing_detail_duplicate()
    test_safety_duplicate_page_stops()
    test_safety_empty_window_does_not_skip_later_horizon()
    test_safety_max_windows_stops()
    test_safety_repeated_ids_across_overlap_still_unique()
    test_generic_extract_still_capped_for_other_sources()
    test_process_source_routes_hkie_events_to_eventlist()
    test_process_source_does_not_steal_other_sources()
    print("ALL HKIE EVENTLIST DISCOVERY TESTS PASSED")
