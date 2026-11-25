"""CIC Main Playwright fallback routing tests.

Run: python scraper/test_cic_playwright_fallback.py

Proves deterministic fallback for CIC Main only. Does not write events.json,
does not call production sources, and must not invoke Scrapling.
"""
import hashlib
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from bs4 import BeautifulSoup

import fetch as fetch_mod
from fetch import (
    apply_cic_main_playwright_fallback,
    cic_event_container_present,
    extract_cic,
    is_cic_main_url,
)
from title_quality import CIC_EVENT_TYPE_LABELS, is_good_title

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS_JSON = os.path.join(ROOT, "events.json")
HEALTH_JSON = os.path.join(ROOT, "source_health.json")
CIC_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cic", "events.html")

CIC_MAIN = {
    "name": "CIC 建造業議會 Events",
    "url": "https://www.cic.hk/en/events",
    "region": "HK",
    "group": "CIC",
}

STATIC_VALID_HTML = """<!DOCTYPE html><html><head><title>Events | Construction Industry Council</title></head>
<body>
<div class="calendar">
  <article class="event-card">
    <h3>CIC Technical Seminar on Site Safety</h3>
    <span class="date">15.12.2026</span>
    <a href="/en/events/site-safety">CIC Technical Seminar on Site Safety</a>
  </article>
</div>
</body></html>
"""

STATIC_EMPTY_HTML = """<!DOCTYPE html><html><head><title>Events | Construction Industry Council</title></head>
<body><div id="app"></div></body></html>
"""

PLAYWRIGHT_VALID_HTML = """<!DOCTYPE html><html><head><title>Events | Construction Industry Council</title></head>
<body>
<div class="calendar">
  <article class="event-card">
    <h3>Work-at-Height Safety Webinar</h3>
    <span class="date">20.12.2026</span>
    <a href="/en/events/wah-safety">Work-at-Height Safety Webinar</a>
  </article>
</div>
</body></html>
"""

PLAYWRIGHT_EMPTY_HTML = """<!DOCTYPE html><html><head><title>Events | Construction Industry Council</title></head>
<body><div id="app"></div></body></html>
"""


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _classify(n, rejects, page_title):
    """Mirror of fetch.main() status rules (unchanged by this hotfix)."""
    if n > 0:
        return "OK_WITH_EVENTS"
    if rejects and all(k in ("date_range", "overseas_physical", "paid", "social") for k in rejects):
        return "VERIFIED_EMPTY"
    title = page_title or ""
    if "under construction" in title.lower() or "page under construction" in title.lower():
        return "VERIFIED_EMPTY"
    return "EMPTY_UNVERIFIED"


class _Patch:
    def __init__(self):
        self._restore = []

    def set(self, name, value):
        self._restore.append((name, getattr(fetch_mod, name)))
        setattr(fetch_mod, name, value)

    def rollback(self):
        for name, value in reversed(self._restore):
            setattr(fetch_mod, name, value)
        self._restore.clear()


def _process(html, playwright_html=None, playwright_exc=None, playwright_ok=True, src=None):
    """Run process_source with static HTML and an optional Playwright render hook."""
    calls = {"playwright": 0, "scrapling": 0, "static": 0, "pw_urls": []}
    p = _Patch()

    def fake_fetch(url, use_playwright=False, session=None):
        calls["static"] += 1
        if use_playwright:
            raise AssertionError("CIC Main must not use the generic fetch_html Playwright retry")
        return html

    def fake_render(url):
        calls["playwright"] += 1
        calls["pw_urls"].append(url)
        if playwright_exc is not None:
            raise playwright_exc
        return playwright_html if playwright_html is not None else PLAYWRIGHT_EMPTY_HTML

    def boom_scrapling(*a, **k):
        calls["scrapling"] += 1
        raise AssertionError("Scrapling must not be invoked in the CIC Main fallback")

    p.set("fetch_html", fake_fetch)
    p.set("PLAYWRIGHT_OK", playwright_ok)
    p.set("_render_cic_main_with_playwright", fake_render)
    # Guard against accidental shadow / scrapling use on this path.
    if hasattr(fetch_mod, "run_scrapling_shadow"):
        p.set("run_scrapling_shadow", boom_scrapling)

    events_before = _sha(EVENTS_JSON) if os.path.exists(EVENTS_JSON) else None
    health_before = _sha(HEALTH_JSON) if os.path.exists(HEALTH_JSON) else None
    try:
        raw, method, title = fetch_mod.process_source(src or CIC_MAIN)
    finally:
        p.rollback()
    events_after = _sha(EVENTS_JSON) if os.path.exists(EVENTS_JSON) else None
    health_after = _sha(HEALTH_JSON) if os.path.exists(HEALTH_JSON) else None
    assert events_before == events_after, "process_source must not write events.json"
    assert health_before == health_after, "process_source must not write source_health.json"
    assert calls["scrapling"] == 0
    return raw, method, title, calls


def test_is_cic_main_url_scope():
    assert is_cic_main_url("https://www.cic.hk/en/events") is True
    assert is_cic_main_url("https://cic.hk/en/events") is True
    assert is_cic_main_url("https://www.bim.cic.hk/en/events/list") is False
    assert is_cic_main_url("https://citac.cic.hk/en-hk/news-and-events/events/upcoming-events") is False
    assert is_cic_main_url("https://rstc.cic.hk/en/events.aspx") is False
    assert is_cic_main_url("https://www.cic.org.uk/events") is False
    print("is_cic_main_url scope OK")


def test_1_static_positive_skips_playwright():
    raw, method, title, calls = _process(STATIC_VALID_HTML, playwright_html=PLAYWRIGHT_VALID_HTML)
    assert calls["playwright"] == 0, "static >0 must not launch Playwright"
    assert method == "cic-list"
    assert any("Site Safety" in e["title"] for e in raw), raw
    print("1 static CIC >0 -> no Playwright needed OK")


def test_2_static_zero_attempts_playwright():
    raw, method, title, calls = _process(STATIC_EMPTY_HTML, playwright_html=PLAYWRIGHT_VALID_HTML)
    assert calls["playwright"] == 1, "static 0 must attempt Playwright"
    assert calls["pw_urls"] == [CIC_MAIN["url"]]
    print("2 static CIC 0 -> Playwright attempted OK")


def test_3_static_zero_playwright_valid_ok_with_events():
    raw, method, title, calls = _process(STATIC_EMPTY_HTML, playwright_html=PLAYWRIGHT_VALID_HTML)
    assert raw, raw
    assert any("Work-at-Height" in e["title"] for e in raw), raw
    st = _classify(len(raw), {}, title)
    assert st == "OK_WITH_EVENTS", st
    print("3 static 0 + Playwright valid -> OK_WITH_EVENTS OK")


def test_4_method_records_playwright_cic_list():
    raw, method, title, calls = _process(STATIC_EMPTY_HTML, playwright_html=PLAYWRIGHT_VALID_HTML)
    assert method == "playwright+cic-list", method
    print("4 method records playwright+cic-list OK")


def test_5_both_zero_empty_unverified():
    raw, method, title, calls = _process(STATIC_EMPTY_HTML, playwright_html=PLAYWRIGHT_EMPTY_HTML)
    assert raw == []
    assert method == "playwright+cic-list", method
    st = _classify(0, {}, title)
    assert st == "EMPTY_UNVERIFIED", st
    assert st != "VERIFIED_EMPTY"
    print("5 both zero -> EMPTY_UNVERIFIED OK")


def test_6_playwright_exception_isolated():
    raw, method, title, calls = _process(
        STATIC_EMPTY_HTML,
        playwright_exc=RuntimeError("browser crashed"),
    )
    assert calls["playwright"] == 1
    assert raw == []
    assert method == "cic-list", method
    st = _classify(0, {}, title)
    assert st == "EMPTY_UNVERIFIED"
    print("6 Playwright exception -> source failure isolated OK")


def test_7_event_types_labels_rejected():
    with open(CIC_FIXTURE, encoding="utf-8") as f:
        fixture_html = f.read()
    raw, method, title, calls = _process(STATIC_EMPTY_HTML, playwright_html=fixture_html)
    titles = [e["title"] for e in raw]
    for label in CIC_EVENT_TYPE_LABELS:
        assert all(t.lower() != label.lower() for t in titles), (label, titles)
    assert "Job Fair" not in titles
    assert "Exhibition" not in titles
    assert "Workshop" not in titles
    assert any("Temporary Works Workshop 2026" in t for t in titles), titles
    print("7 Event Types labels rejected OK", titles)


def test_8_previous_valid_events_preserved_when_both_fail():
    raw, method, title, calls = _process(STATIC_EMPTY_HTML, playwright_html=PLAYWRIGHT_EMPTY_HTML)
    assert raw == []
    src = inspect.getsource(fetch_mod.main)
    assert 'if e.get("auto") and e.get("date", "") >= cutoff and e.get("id") not in found:' in src
    assert "Dropped" in src and "stale contaminated" in src
    # The existing merge keeps prior auto events whose ids were not refreshed.
    old = [{
        "id": "cic-preserved-1",
        "name": "CIC Technical Seminar on Site Safety",
        "date": "2026-12-15",
        "auto": True,
        "org": "CIC",
    }]
    found = {}
    cutoff = "2026-10-01"
    preserved = []
    for e in old:
        if e.get("auto") and e.get("date", "") >= cutoff and e.get("id") not in found:
            if not is_good_title(e.get("name") or ""):
                continue
            found[e["id"]] = e
            preserved.append(e)
    assert preserved and found["cic-preserved-1"]["name"] == "CIC Technical Seminar on Site Safety"
    print("8 previous valid events preserved when both fail OK")


def test_9_other_sources_unaffected():
    # BIM shares the cic-list extractor but is not CIC Main — dedicated hook must not run.
    bim = {
        "name": "CIC BIM Events",
        "url": "https://www.bim.cic.hk/en/events/list",
        "region": "HK",
        "group": "CIC",
    }
    raw, method, title, calls = _process(
        STATIC_VALID_HTML,
        playwright_html=PLAYWRIGHT_VALID_HTML,
        src=bim,
    )
    assert calls["playwright"] == 0, "CIC Main Playwright hook must not run for BIM"
    assert method == "cic-list", method
    assert raw, raw

    # A static-positive CIC Main already covered; also a non-CIC source.
    hkgbc = {
        "name": "HKGBC Events",
        "url": "https://www.hkgbc.org.hk/eng/events",
        "region": "HK",
    }
    p = _Patch()
    hook_calls = []

    def fake_fetch(url, use_playwright=False, session=None):
        return "<html><head><title>HKGBC</title></head><body></body></html>"

    def fake_render(url):
        hook_calls.append(url)
        raise AssertionError("CIC Main Playwright must not run for HKGBC")

    def fake_hkgbc(soup, url, fetch_detail=None):
        return [{"title": "HKGBC Green Webinar", "date": "2026-12-01", "url": url, "organizer": "HKGBC"}]

    p.set("fetch_html", fake_fetch)
    p.set("PLAYWRIGHT_OK", True)
    p.set("_render_cic_main_with_playwright", fake_render)
    p.set("extract_hkgbc", fake_hkgbc)
    try:
        raw2, method2, title2 = fetch_mod.process_source(hkgbc)
    finally:
        p.rollback()
    assert hook_calls == []
    assert method2 == "hkgbc", method2
    assert len(raw2) == 1
    print("9 other sources unaffected OK")


def test_10_scrapling_not_invoked():
    fallback_src = inspect.getsource(apply_cic_main_playwright_fallback)
    render_src = inspect.getsource(fetch_mod._render_cic_main_with_playwright)
    branch_src = inspect.getsource(fetch_mod.process_source)
    for src in (fallback_src, render_src, branch_src):
        low = src.lower()
        assert "import scrapling" not in low, src
        assert "from scrapling" not in low, src
        assert "run_scrapling" not in low, src
        assert "scrapling_shadow" not in low, src
    import sys as _sys
    class _Boom:
        def __getattr__(self, name):
            raise AssertionError(f"Scrapling must not be imported/invoked: {name}")
    saved = {k: _sys.modules.get(k) for k in ("scrapling", "scraper.shadow.scrapling_shadow")}
    _sys.modules["scrapling"] = _Boom()
    _sys.modules["scraper.shadow.scrapling_shadow"] = _Boom()
    try:
        raw, method, title, calls = _process(STATIC_EMPTY_HTML, playwright_html=PLAYWRIGHT_VALID_HTML)
        assert raw and method == "playwright+cic-list"
    finally:
        for k, v in saved.items():
            if v is None:
                _sys.modules.pop(k, None)
            else:
                _sys.modules[k] = v
    print("10 Scrapling not invoked OK")


def test_container_absent_triggers_playwright_even_if_legacy_raw():
    # Legacy line-scan HTML with no event container should still attempt Playwright.
    legacy = """<!DOCTYPE html><html><head><title>Events | Construction Industry Council</title></head>
<body><pre>15.12.2026 CIC Technical Seminar on Site Safety</pre></body></html>
"""
    raw, method, title, calls = _process(legacy, playwright_html=PLAYWRIGHT_VALID_HTML)
    assert calls["playwright"] == 1
    assert method == "playwright+cic-list"
    assert any("Work-at-Height" in e["title"] for e in raw)
    print("container absent triggers Playwright OK")


def test_extract_cic_container_helper():
    soup = BeautifulSoup(STATIC_VALID_HTML, "html.parser")
    assert cic_event_container_present(soup) is True
    soup2 = BeautifulSoup(STATIC_EMPTY_HTML, "html.parser")
    assert cic_event_container_present(soup2) is False
    # Filter-only chrome is not a container
    soup3 = BeautifulSoup(
        "<select><option>Workshop</option></select>",
        "html.parser",
    )
    assert cic_event_container_present(soup3) is False
    print("container helper OK")


if __name__ == "__main__":
    test_is_cic_main_url_scope()
    test_1_static_positive_skips_playwright()
    test_2_static_zero_attempts_playwright()
    test_3_static_zero_playwright_valid_ok_with_events()
    test_4_method_records_playwright_cic_list()
    test_5_both_zero_empty_unverified()
    test_6_playwright_exception_isolated()
    test_7_event_types_labels_rejected()
    test_8_previous_valid_events_preserved_when_both_fail()
    test_9_other_sources_unaffected()
    test_10_scrapling_not_invoked()
    test_container_absent_triggers_playwright_even_if_legacy_raw()
    test_extract_cic_container_helper()
    print("ALL CIC Playwright fallback tests passed")
