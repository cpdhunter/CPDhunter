"""HKIE CPD Scrapling production-canary tests (Step 11, tests 1–20 + disable switch)."""
from __future__ import annotations

import copy
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRAPER = Path(__file__).resolve().parent
for p in (str(ROOT), str(SCRAPER)):
    if p not in sys.path:
        sys.path.insert(0, p)

from bs4 import BeautifulSoup  # noqa: E402

from event_mode import attach_mode  # noqa: E402
from fetch import clean, dedup_events, extract_cic, extract_hkgbc, extract_hkie_cpd  # noqa: E402
from hkie_cpd_canary import (  # noqa: E402
    CANARY_FAIL,
    CANARY_PASS_LEGACY,
    CANARY_PASS_SCRAPLING,
    CANARY_REVIEW,
    attach_health_diagnostic,
    canary_enabled,
    canary_stage,
    choose_result_set,
    evaluate_canary,
    extract_hkie_cpd_with_canary,
    is_official_hkie_course_url,
    last_diagnostic,
    legacy_hkie_cpd_extract,
    reset_last_diagnostic,
    scrapling_hkie_cpd_extract,
    to_legacy_raw,
)
from title_quality import is_date_only_title, is_good_title  # noqa: E402

from scraper.shadow.adaptive import (  # noqa: E402
    AUTO_MATCH_FAILED,
    AUTO_MATCH_RECOVERED,
    run_adaptive_case,
)
from scraper.shadow.build_fixtures import build_all  # noqa: E402
from scraper.shadow.paths import (  # noqa: E402
    CSS_HKIE_CARD,
    HKIE_DECOY,
    HKIE_DRIFT,
    HKIE_URL,
    IDENT_HKIE_CARD,
    PRODUCTION_HKIE,
    SOURCE_LABEL_HKIE,
)

HKIE_SRC = {
    "name": "HKIE CPD Calendar",
    "url": HKIE_URL,
    "region": "HK",
    "free": None,
    "group": "HKIE",
    "type": "Technical",
}

FIXTURE_HTML = Path(PRODUCTION_HKIE).read_text(encoding="utf-8")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _card(title: str, date: str, href: str, time_s: str = "", hours: str = "", cls: str = "e-loop-item") -> str:
    time_html = f'<span class="elementor-icon-list-text">{time_s}</span>' if time_s else ""
    hours_html = f"<div>{hours}</div>" if hours else ""
    return f"""
<div class="{cls}">
  <div class="elementor-heading-title">CPD9999/2026</div>
  <h2 class="elementor-heading-title"><a href="{href}">{title}</a></h2>
  <span class="elementor-icon-list-text">{date}</span>
  {time_html}
  {hours_html}
</div>
"""


def _page(*cards: str, extra: str = "") -> str:
    return "<!DOCTYPE html><html><body><div class='loop'>" + extra + "".join(cards) + "</div></body></html>"


def _state():
    td = tempfile.TemporaryDirectory()
    return td, os.path.join(td.name, "hkie.json")


def _evt(title, date, url, **extra):
    ev = {"title": title, "date": date, "url": url, "organizer": "HKIE"}
    ev.update(extra)
    return ev


COURSE_A = "Organizational Level Greenhouse Gas Accounting Course For Engineers"
COURSE_B = "Essentials of NEC4 Engineering Construction Contract Workshop"
URL_A = "https://hkie.org.hk/cpd-courses/iso-14064-course/"
URL_B = "https://hkie.org.hk/cpd-courses/essentials-of-nec4-workshop/"


# ---------------------------------------------------------------------------
# 1–2 fixture agreement
# ---------------------------------------------------------------------------
def test_01_legacy_and_scrapling_same_10_event_fixture():
    soup = _soup(FIXTURE_HTML)
    td, state = _state()
    with td:
        legacy = legacy_hkie_cpd_extract(soup, HKIE_URL)
        shadow = scrapling_hkie_cpd_extract(FIXTURE_HTML, HKIE_URL, storage_file=state)
    events = shadow["events"]
    assert shadow.get("error") is None, shadow
    assert len(legacy) == 10, [e["title"] for e in legacy]
    assert len(events) == 10, [e["title"] for e in events]
    print("test_01_legacy_and_scrapling_same_10_event_fixture OK", len(legacy), len(events))
    return legacy, events


def test_02_exact_title_date_agreement():
    soup = _soup(FIXTURE_HTML)
    td, state = _state()
    with td:
        legacy = legacy_hkie_cpd_extract(soup, HKIE_URL)
        events = scrapling_hkie_cpd_extract(FIXTURE_HTML, HKIE_URL, storage_file=state)["events"]
    def key(e):
        return (" ".join((e.get("title") or "").split()).lower(), e.get("date"))
    assert {key(e) for e in legacy} == {key(e) for e in events}
    decision = evaluate_canary(legacy, events)
    assert decision["title_mismatches"] == 0, decision
    assert decision["date_mismatches"] == 0, decision
    assert decision["matched_count"] == 10, decision
    assert decision["legacy_only"] == 0 and decision["scrapling_only"] == 0
    assert decision["canary_status"] == CANARY_PASS_LEGACY, decision
    assert decision["material_benefit"] is False
    print("test_02_exact_title_date_agreement OK")


# ---------------------------------------------------------------------------
# 3–4 adaptive cases (reuse shadow drift/decoy fixtures)
# ---------------------------------------------------------------------------
def test_03_wrapper_drift_adaptive_recovery():
    build_all()
    with tempfile.TemporaryDirectory() as td:
        result = run_adaptive_case(
            baseline_html=FIXTURE_HTML,
            trial_html=Path(HKIE_DRIFT).read_text(encoding="utf-8"),
            url=HKIE_URL,
            storage_file=os.path.join(td, "hkie.json"),
            css=CSS_HKIE_CARD,
            identifier=IDENT_HKIE_CARD,
            expected_text_contains="Organizational Level Greenhouse Gas Accounting",
            prefer_text_contains="Organizational Level Greenhouse Gas Accounting",
        )
    assert result["original_selector_failed"]
    assert result["status"] == AUTO_MATCH_RECOVERED, result
    assert result["correct_event"] is True
    # Recovered node must also pass minimum HKIE event structure (not FP).
    assert "Organizational Level Greenhouse Gas Accounting" in (result.get("recovered_text") or "")
    print("test_03_wrapper_drift_adaptive_recovery OK")


def test_04_sidebar_lure_adaptive_failure():
    build_all()
    with tempfile.TemporaryDirectory() as td:
        result = run_adaptive_case(
            baseline_html=FIXTURE_HTML,
            trial_html=Path(HKIE_DECOY).read_text(encoding="utf-8"),
            url=HKIE_URL,
            storage_file=os.path.join(td, "hkie.json"),
            css=CSS_HKIE_CARD,
            identifier=IDENT_HKIE_CARD,
            expected_text_contains="Organizational Level Greenhouse Gas Accounting",
            prefer_text_contains="Organizational Level Greenhouse Gas Accounting",
        )
    assert result["original_selector_failed"]
    assert result["status"] == AUTO_MATCH_FAILED, result
    # If a sidebar node *were* returned, GATE D must fail the canary.
    decision = evaluate_canary(
        [_evt(COURSE_A, "2026-12-09", URL_A)],
        [],
        meta={"adaptive_status": "AUTO_MATCH_FALSE_POSITIVE", "adaptive_false_positive_count": 1},
    )
    assert decision["canary_status"] == CANARY_FAIL
    assert decision["gates"]["D"] == "FAIL"
    selected, parser, status = choose_result_set(
        [_evt(COURSE_A, "2026-12-09", URL_A)], [], decision, stage=2
    )
    assert parser == "legacy" and status == CANARY_FAIL
    print("test_04_sidebar_lure_adaptive_failure OK")


# ---------------------------------------------------------------------------
# 5–7 parser + gate rejections
# ---------------------------------------------------------------------------
def test_05_date_only_title_rejected():
    html = _page(
        _card("11 Dec 2026 (Fri)", "11 Dec 2026 (Fri)", "https://hkie.org.hk/cpd-courses/date-only/"),
        _card(COURSE_A, "9 Dec 2026 (Wed)", URL_A, "09:30 – 17:30"),
    )
    td, state = _state()
    with td:
        events = scrapling_hkie_cpd_extract(html, HKIE_URL, storage_file=state)["events"]
    titles = [e["title"] for e in events]
    assert COURSE_A in " ".join(titles)
    for t in titles:
        assert not is_date_only_title(t), t
        assert is_good_title(t), t
    # Gate rejects a leaked date-only title if a parser ever emitted one.
    bad = [_evt("11 Dec 2026", "2026-12-11", URL_A)]
    decision = evaluate_canary([_evt(COURSE_A, "2026-12-09", URL_A)], bad)
    assert decision["canary_status"] == CANARY_FAIL
    assert decision["gates"]["A"] == "FAIL"
    print("test_05_date_only_title_rejected OK")


def test_06_adjacent_card_title_date_mismatch_rejected():
    html = _page(
        _card(COURSE_A, "9 Dec 2026 (Wed)", URL_A, "09:30 – 17:30"),
        _card(COURSE_B, "11 Dec 2026 (Fri)", URL_B, "09:00 – 17:00"),
    )
    td, state = _state()
    with td:
        soup = _soup(html)
        legacy = legacy_hkie_cpd_extract(soup, HKIE_URL)
        events = scrapling_hkie_cpd_extract(html, HKIE_URL, storage_file=state)["events"]
    a = next(e for e in events if COURSE_A[:20] in e["title"])
    b = next(e for e in events if "NEC4" in e["title"])
    assert a["date"] == "2026-12-09", a
    assert b["date"] == "2026-12-11", b
    # Swapped dates (adjacent-card pairing) must fail the canary and use legacy.
    swapped = [
        _evt(a["title"], b["date"], a["url"]),
        _evt(b["title"], a["date"], b["url"]),
    ]
    decision = evaluate_canary(legacy or [_evt(COURSE_A, "2026-12-09", URL_A), _evt(COURSE_B, "2026-12-11", URL_B)], swapped)
    assert decision["date_mismatches"] >= 1, decision
    assert decision["canary_status"] == CANARY_FAIL
    assert decision["gates"]["F"] == "FAIL"
    raw, parser, _ = choose_result_set(legacy, swapped, decision, stage=2)
    assert parser == "legacy"
    assert raw is not swapped
    print("test_06_adjacent_card_title_date_mismatch_rejected OK")


def test_07_generic_heading_rejected():
    heading = """
    <div class="e-loop-item">
      <h2 class="elementor-heading-title">CPD Calendar</h2>
      <span class="elementor-icon-list-text">11 Dec 2026 (Fri)</span>
    </div>
    """
    html = _page(_card(COURSE_A, "9 Dec 2026 (Wed)", URL_A), extra=heading)
    td, state = _state()
    with td:
        events = scrapling_hkie_cpd_extract(html, HKIE_URL, storage_file=state)["events"]
    titles = [e["title"] for e in events]
    assert all(t.lower() != "cpd calendar" for t in titles), titles
    decision = evaluate_canary(
        [_evt(COURSE_A, "2026-12-09", URL_A)],
        [_evt("CPD Calendar", "2026-12-11", "https://hkie.org.hk/professional-development/continuing-professional-development/cpd-calendar/")],
    )
    assert decision["canary_status"] == CANARY_FAIL
    assert decision["gates"]["A"] == "FAIL"
    print("test_07_generic_heading_rejected OK")


# ---------------------------------------------------------------------------
# 8–13 fallbacks
# ---------------------------------------------------------------------------
def _ok_pair(n=3):
    legacy = [_evt(f"{COURSE_A} Session {i}", f"2026-12-{10+i:02d}", f"https://hkie.org.hk/cpd-courses/sess-{i}/") for i in range(n)]
    return legacy, copy.deepcopy(legacy)


def test_08_scrapling_zero_legacy_nonzero_uses_legacy():
    legacy, _ = _ok_pair(3)
    decision = evaluate_canary(legacy, [])
    assert decision["canary_status"] == CANARY_REVIEW
    assert decision["gates"]["E"] == "REVIEW"
    raw, parser, _ = choose_result_set(legacy, [], decision, stage=2)
    assert parser == "legacy"
    assert [e["title"] for e in raw] == [e["title"] for e in legacy]
    print("test_08_scrapling_zero_legacy_nonzero_uses_legacy OK")


def test_09_scrapling_candidate_explosion_uses_legacy():
    legacy, _ = _ok_pair(4)
    boom = legacy + [_evt(f"Extra Valid Engineering Course Number {i}", f"2026-12-{20+i:02d}", f"https://hkie.org.hk/cpd-courses/x-{i}/") for i in range(10)]
    decision = evaluate_canary(legacy, boom)
    assert len(boom) > max(len(legacy) * 1.5, len(legacy) + 5)
    assert decision["canary_status"] == CANARY_REVIEW
    assert decision["gates"]["E"] == "REVIEW"
    raw, parser, _ = choose_result_set(legacy, boom, decision, stage=2)
    assert parser == "legacy" and len(raw) == len(legacy)
    print("test_09_scrapling_candidate_explosion_uses_legacy OK")


def test_10_unexplained_date_mismatch_uses_legacy():
    legacy, scrap = _ok_pair(3)
    scrap[1] = {**scrap[1], "date": "2026-01-01"}
    decision = evaluate_canary(legacy, scrap)
    assert decision["date_mismatches"] >= 1
    assert decision["canary_status"] == CANARY_FAIL
    raw, parser, _ = choose_result_set(legacy, scrap, decision, stage=2)
    assert parser == "legacy"
    print("test_10_unexplained_date_mismatch_uses_legacy OK")


def test_11_small_explainable_result_difference_can_pass():
    legacy, scrap = _ok_pair(4)
    extra = _evt("Additional Valid Professional Engineering Workshop", "2026-12-28", "https://hkie.org.hk/cpd-courses/extra-workshop/")
    scrap = scrap + [extra]
    decision = evaluate_canary(legacy, scrap)
    assert decision["canary_status"] in (CANARY_PASS_LEGACY, CANARY_PASS_SCRAPLING), decision
    assert decision["gates"]["E"] == "PASS", decision
    assert decision["date_mismatches"] == 0
    print("test_11_small_explainable_result_difference_can_pass OK", decision["canary_status"])


def test_12_scrapling_exception_uses_legacy():
    soup = _soup(FIXTURE_HTML)
    legacy = legacy_hkie_cpd_extract(soup, HKIE_URL)
    td, state = _state()
    with td, mock.patch("hkie_cpd_canary.scrapling_hkie_cpd_extract", side_effect=RuntimeError("boom")):
        raw, method = extract_hkie_cpd_with_canary(soup, HKIE_URL, html=FIXTURE_HTML, storage_file=state)
    assert method == "hkie-cpd"
    assert [e["title"] for e in raw] == [e["title"] for e in legacy]
    diag = last_diagnostic()
    assert diag["selected_result"] == "legacy"
    assert diag["canary_status"] == CANARY_FAIL
    assert "RuntimeError" in (diag["reason"] or "") or "boom" in (diag.get("reason") or "")
    print("test_12_scrapling_exception_uses_legacy OK")


def test_13_adaptive_state_unavailable_uses_legacy():
    soup = _soup(FIXTURE_HTML)
    legacy = legacy_hkie_cpd_extract(soup, HKIE_URL)
    # A storage path whose parent cannot be created forces an extract error.
    bad_state = os.path.join("/dev/null", "not-a-dir", "hkie.json")
    extracted = scrapling_hkie_cpd_extract(FIXTURE_HTML, HKIE_URL, storage_file=bad_state)
    # Whether CSS still works without state, or the extract errors, production
    # must not crash and must keep legacy when state is required/unavailable.
    if extracted.get("error"):
        decision = evaluate_canary(legacy, extracted.get("events") or [], meta={"error": extracted["error"]})
        assert decision["canary_status"] == CANARY_FAIL
        raw, parser, _ = choose_result_set(legacy, [], decision, stage=2)
        assert parser == "legacy"
    else:
        # CSS path succeeded without adaptive state — still a safe legacy-or-pass outcome.
        with mock.patch("hkie_cpd_canary.scrapling_hkie_cpd_extract", return_value={
            "events": [],
            "error": "adaptive state unavailable",
            "adaptive_match_used": False,
            "adaptive_recovery_count": 0,
            "adaptive_false_positive_count": 0,
            "state_bytes": 0,
        }):
            raw, method = extract_hkie_cpd_with_canary(soup, HKIE_URL, html=FIXTURE_HTML, storage_file=bad_state)
        assert method == "hkie-cpd"
        assert [e["title"] for e in raw] == [e["title"] for e in legacy]
        assert last_diagnostic()["selected_result"] == "legacy"
    print("test_13_adaptive_state_unavailable_uses_legacy OK")


# ---------------------------------------------------------------------------
# 14–15 clean/dedup once, no A+B inflation
# ---------------------------------------------------------------------------
def test_14_selected_scrapling_enters_clean_dedup_only_once():
    soup = _soup(FIXTURE_HTML)
    td, state = _state()
    with td:
        raw, method = extract_hkie_cpd_with_canary(soup, HKIE_URL, html=FIXTURE_HTML, storage_file=state)
    # Stage 1 selects legacy. Simulate a Stage-2 scrapling-selected set.
    scrap = scrapling_hkie_cpd_extract(FIXTURE_HTML, HKIE_URL, storage_file=os.path.join(tempfile.mkdtemp(), "s.json"))["events"]
    decision = {
        "canary_status": CANARY_PASS_SCRAPLING,
        "would_select": "scrapling",
        "material_benefit": True,
        "reason": "forced",
    }
    selected, parser, _ = choose_result_set(raw, scrap, decision, stage=2)
    assert parser == "scrapling"
    rejects = {}
    cleaned = []
    for e in selected:
        c = clean(e, HKIE_SRC, rejects)
        if c:
            cleaned.append(c)
    once = dedup_events(cleaned)
    twice = dedup_events(dedup_events(cleaned))
    assert len(once) == len(twice)
    assert len(once) == len(cleaned)  # already unique by date+title
    print("test_14_selected_scrapling_enters_clean_dedup_only_once OK", len(once))


def test_15_no_ab_duplicate_inflation():
    soup = _soup(FIXTURE_HTML)
    td, state = _state()
    with td:
        legacy = legacy_hkie_cpd_extract(soup, HKIE_URL)
        scrap = scrapling_hkie_cpd_extract(FIXTURE_HTML, HKIE_URL, storage_file=state)["events"]
        raw, _ = extract_hkie_cpd_with_canary(soup, HKIE_URL, html=FIXTURE_HTML, storage_file=state)
    # The hook returns one complete set, never the concatenation.
    assert len(raw) != len(legacy) + len(scrap)
    assert len(raw) == len(legacy)  # Stage 1 default
    rejects = {}
    cleaned = [c for e in raw if (c := clean(e, HKIE_SRC, rejects))]
    # Even if someone concatenated A+B, dedup should not be our production path;
    # assert the selected set itself is not inflated.
    assert len(cleaned) == 10
    merged = copy.deepcopy(legacy) + copy.deepcopy(scrap)
    assert len(merged) == 20
    print("test_15_no_ab_duplicate_inflation OK")


# ---------------------------------------------------------------------------
# 16–18 metadata + title quality
# ---------------------------------------------------------------------------
def test_16_registration_metadata_preserved():
    dest = "https://docs.google.com/forms/d/e/1FAIpQLSeePTX0FOAtykLZya98GGUnHNJ6Qep2vSFutiZq7H1TLTyNkQ/viewform"
    raw = to_legacy_raw(_evt(COURSE_A, "2026-12-09", URL_A, registration_destination=dest))
    assert raw["registration_destination"] == dest
    rejects = {}
    cleaned = clean(raw, HKIE_SRC, rejects)
    assert cleaned, rejects
    assert cleaned["registration"]["destination"] == dest
    assert cleaned["registration"]["mechanism"] == "GOOGLE_FORMS"
    print("test_16_registration_metadata_preserved OK")


def test_17_mode_metadata_preserved():
    raw = to_legacy_raw(_evt(COURSE_A, "2026-12-09", URL_A, mode="HYBRID", modeText="Hybrid (face-to-face and online)"))
    assert raw["mode"] == "HYBRID"
    rejects = {}
    cleaned = clean(raw, HKIE_SRC, rejects)
    assert cleaned and cleaned["mode"] == "HYBRID"
    # UNKNOWN must not be invented / written through.
    unknown = to_legacy_raw(_evt(COURSE_B, "2026-12-11", URL_B, mode="UNKNOWN"))
    assert "mode" not in unknown
    cleaned2 = clean(unknown, HKIE_SRC, {})
    attach_mode(cleaned2)
    # No reliable evidence → mode field stays absent (not invented).
    assert cleaned2.get("mode") in (None, "UNKNOWN")
    if "mode" in cleaned2:
        # attach_mode only writes non-UNKNOWN, so this should be absent.
        raise AssertionError("UNKNOWN mode should not be stamped onto the event")
    print("test_17_mode_metadata_preserved OK")


def test_18_title_quality_validator_still_passes():
    soup = _soup(FIXTURE_HTML)
    td, state = _state()
    with td:
        raw, _ = extract_hkie_cpd_with_canary(soup, HKIE_URL, html=FIXTURE_HTML, storage_file=state)
    for e in raw:
        assert is_good_title(e["title"]), e
        assert not is_date_only_title(e["title"])
    rejects = {}
    cleaned = [clean(e, HKIE_SRC, rejects) for e in raw]
    assert all(c and is_good_title(c["name"]) for c in cleaned), rejects
    print("test_18_title_quality_validator_still_passes OK")


# ---------------------------------------------------------------------------
# 19–20 source-health + other sources
# ---------------------------------------------------------------------------
def test_19_source_health_remains_valid():
    reset_last_diagnostic()
    soup = _soup(FIXTURE_HTML)
    td, state = _state()
    with td:
        extract_hkie_cpd_with_canary(soup, HKIE_URL, html=FIXTURE_HTML, storage_file=state)
    health = {
        SOURCE_LABEL_HKIE: {
            "last_status": "OK_WITH_EVENTS",
            "last_n": 10,
            "last_method": "hkie-cpd",
            "last_error": None,
            "raw_candidates": 10,
            "rejects": {},
            "consecutive_fail": 0,
            "last_success": "2026-11-16",
            "updated": "2026-11-16",
        }
    }
    before = copy.deepcopy(health[SOURCE_LABEL_HKIE])
    attach_health_diagnostic(health)
    entry = health[SOURCE_LABEL_HKIE]
    for key in before:
        assert entry[key] == before[key], (key, entry[key], before[key])
    assert "canary" in entry
    canary = entry["canary"]
    assert canary["selected_result"] == "legacy"
    assert canary["canary_status"] in (CANARY_PASS_LEGACY, CANARY_PASS_SCRAPLING, CANARY_REVIEW, CANARY_FAIL)
    assert set(canary).isdisjoint({"last_status", "consecutive_fail"})
    print("test_19_source_health_remains_valid OK", canary["canary_status"])


def test_20_other_sources_unaffected():
    text = Path(SCRAPER, "fetch.py").read_text(encoding="utf-8")
    assert 'raw = extract_cic(soup, url)' in text
    assert 'raw = extract_hkgbc(soup, url, fetch_detail=_hkgbc_fetch)' in text
    # Canary hook is only on the HKIE CPD calendar branches.
    assert "extract_hkie_cpd_with_canary" in text
    cic_block = text.split('elif "cic.hk" in url')[1].split('elif "hkgbc" in url')[0]
    hkgbc_block = text.split('elif "hkgbc" in url')[1].split('elif "ciphe.org.hk" in url')[0]
    assert "extract_hkie_cpd_with_canary" not in cic_block
    assert "extract_hkie_cpd_with_canary" not in hkgbc_block
    assert "extract_hkie_cpd_with_canary" not in inspect.getsource(extract_cic)
    assert "extract_hkie_cpd_with_canary" not in inspect.getsource(extract_hkgbc)
    canary_src = Path(SCRAPER, "hkie_cpd_canary.py").read_text(encoding="utf-8")
    assert "extract_cic" not in canary_src
    assert "extract_hkgbc" not in canary_src
    print("test_20_other_sources_unaffected OK")


def test_disable_canary_switch_restores_legacy_only():
    soup = _soup(FIXTURE_HTML)
    legacy = extract_hkie_cpd(soup, HKIE_URL)
    td, state = _state()
    with td, mock.patch.dict(os.environ, {"HKIE_SCRAPLING_CANARY": "false"}, clear=False):
        assert canary_enabled() is False
        with mock.patch("hkie_cpd_canary.scrapling_hkie_cpd_extract") as spy:
            raw, method = extract_hkie_cpd_with_canary(soup, HKIE_URL, html=FIXTURE_HTML, storage_file=state)
            spy.assert_not_called()
    assert method == "hkie-cpd"
    assert [e["title"] for e in raw] == [e["title"] for e in legacy]
    assert last_diagnostic()["canary_status"] == "CANARY_DISABLED"
    assert last_diagnostic()["selected_result"] == "legacy"
    print("test_disable_canary_switch_restores_legacy_only OK")


def test_stage1_never_selects_scrapling_even_if_gates_pass():
    legacy, scrap = _ok_pair(3)
    extra = _evt("Additional Valid Professional Engineering Workshop", "2026-12-28", "https://hkie.org.hk/cpd-courses/extra-workshop/")
    decision = evaluate_canary(legacy, scrap + [extra])
    # Might be PASS_SCRAPLING due to small extra event benefit.
    raw, parser, status = choose_result_set(legacy, scrap + [extra], decision, stage=1)
    assert parser == "legacy"
    assert len(raw) == len(legacy)
    print("test_stage1_never_selects_scrapling_even_if_gates_pass OK", decision["canary_status"], status)


def test_official_url_gate():
    listing = HKIE_URL
    assert is_official_hkie_course_url(URL_A, listing)
    assert is_official_hkie_course_url(listing, listing)
    assert is_official_hkie_course_url(None, listing)
    assert not is_official_hkie_course_url("https://hkie.org.hk/membership/", listing)
    assert not is_official_hkie_course_url("https://example.com/cpd-courses/x/", listing)
    print("test_official_url_gate OK")


def main() -> int:
    tests = [
        test_01_legacy_and_scrapling_same_10_event_fixture,
        test_02_exact_title_date_agreement,
        test_03_wrapper_drift_adaptive_recovery,
        test_04_sidebar_lure_adaptive_failure,
        test_05_date_only_title_rejected,
        test_06_adjacent_card_title_date_mismatch_rejected,
        test_07_generic_heading_rejected,
        test_08_scrapling_zero_legacy_nonzero_uses_legacy,
        test_09_scrapling_candidate_explosion_uses_legacy,
        test_10_unexplained_date_mismatch_uses_legacy,
        test_11_small_explainable_result_difference_can_pass,
        test_12_scrapling_exception_uses_legacy,
        test_13_adaptive_state_unavailable_uses_legacy,
        test_14_selected_scrapling_enters_clean_dedup_only_once,
        test_15_no_ab_duplicate_inflation,
        test_16_registration_metadata_preserved,
        test_17_mode_metadata_preserved,
        test_18_title_quality_validator_still_passes,
        test_19_source_health_remains_valid,
        test_20_other_sources_unaffected,
        test_disable_canary_switch_restores_legacy_only,
        test_stage1_never_selects_scrapling_even_if_gates_pass,
        test_official_url_gate,
    ]
    failed = []
    for fn in tests:
        reset_last_diagnostic()
        try:
            fn()
        except Exception as ex:
            failed.append((fn.__name__, ex))
            print(f"FAIL {fn.__name__}: {type(ex).__name__}: {ex}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    if failed:
        print(f"{len(failed)} canary test(s) failed")
        return 1
    print(f"All {len(tests)} HKIE CPD canary tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
