"""Run the experimental Scrapling shadow pilot (comparison + report only).

This script must never write events.json, source_health.json, or any
production catalog / GitHub Pages data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from typing import Any, Callable, Dict, Optional

# Allow `python scraper/shadow/scrapling_shadow.py` from the repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRAPER = os.path.dirname(_HERE)
_REPO = os.path.dirname(_SCRAPER)
if _HERE not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))  # scraper/
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from bs4 import BeautifulSoup  # noqa: E402

from scraper.shadow.adaptive import (  # noqa: E402
    AUTO_MATCH_FAILED,
    AUTO_MATCH_FALSE_POSITIVE,
    AUTO_MATCH_RECOVERED,
    run_adaptive_case,
)
from scraper.shadow.build_fixtures import build_all  # noqa: E402
from scraper.shadow.compare_shadow import pair_events  # noqa: E402
from scraper.shadow.paths import (  # noqa: E402
    ARTIFACTS_DIR,
    CIC_DECOY,
    CIC_DRIFT,
    CIC_URL,
    CSS_CIC_CARD,
    CSS_HKGBC_CARD,
    CSS_HKIE_CARD,
    HKGBC_DECOY,
    HKGBC_DRIFT,
    HKGBC_URL,
    HKIE_DECOY,
    HKIE_DRIFT,
    HKIE_URL,
    IDENT_CIC_CARD,
    IDENT_HKGBC_CARD,
    IDENT_HKIE_CARD,
    PRODUCTION_CIC,
    PRODUCTION_HKGBC,
    PRODUCTION_HKGBC_DETAIL,
    PRODUCTION_HKIE,
    SHADOW_REPORT,
    STATE_CIC,
    STATE_HKGBC,
    STATE_HKIE,
)
from scraper.shadow.observation import (  # noqa: E402
    build_run_record,
    detect_commit,
    detect_python_version,
    write_observation_run,
)
from scraper.shadow.safety import (  # noqa: E402
    assert_production_unchanged,
    snapshot_production,
)
from scraper.shadow.scrapling_cic import parse_cic_html  # noqa: E402
from scraper.shadow.scrapling_hkgbc import parse_hkgbc_html  # noqa: E402
from scraper.shadow.scrapling_hkie_cpd import parse_hkie_cpd_html  # noqa: E402

HKT = dt.timezone(dt.timedelta(hours=8))


def _scrapling_version() -> str:
    try:
        import importlib.metadata as m
        return m.version("scrapling")
    except Exception:
        return "unknown"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _hkgbc_fetch_detail_from_fixtures() -> Callable[[str], str]:
    detail = _read(PRODUCTION_HKGBC_DETAIL)

    def fetch_detail(url: str) -> str:
        if "9001" in url:
            return detail
        raise RuntimeError("no fixture detail for " + url)

    return fetch_detail


def _production_events(source: str, html: str, base: str, fetch_detail=None):
    # Import production parsers only (never call fetch.main / write outputs).
    if _SCRAPER not in sys.path:
        sys.path.insert(0, _SCRAPER)
    from fetch import extract_cic, extract_hkgbc, extract_hkie_cpd

    soup = BeautifulSoup(html, "html.parser")
    if source == "cic":
        return extract_cic(soup, base)
    if source == "hkie_cpd":
        return extract_hkie_cpd(soup, base)
    if source == "hkgbc":
        return extract_hkgbc(soup, base, fetch_detail=fetch_detail)
    raise ValueError(source)


def _live_fetch(url: str, timeout: int = 20) -> Dict[str, Any]:
    """Polite HTTP GET using production helpers. No Playwright, no stealth."""
    if _SCRAPER not in sys.path:
        sys.path.insert(0, _SCRAPER)
    from fetch import StepError, fetch_html

    t0 = time.perf_counter()
    try:
        html = fetch_html(url, use_playwright=False)
        ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": True, "html": html, "status": "http_ok", "fetch_duration_ms": ms, "rendering_used": False}
    except StepError as ex:
        ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": False, "html": None, "status": str(ex), "fetch_duration_ms": ms, "rendering_used": False}
    except Exception as ex:
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "html": None,
            "status": f"{type(ex).__name__}: {ex}",
            "fetch_duration_ms": ms,
            "rendering_used": False,
        }


def _adaptive_pair(source_key: str) -> Dict[str, Any]:
    if source_key == "cic":
        return dict(
            baseline_html=_read(PRODUCTION_CIC),
            drift_html=_read(CIC_DRIFT),
            decoy_html=_read(CIC_DECOY),
            url=CIC_URL,
            css=CSS_CIC_CARD,
            identifier=IDENT_CIC_CARD,
            expected="Temporary Works Workshop 2026",
            prefer="Temporary Works Workshop 2026",
            state=STATE_CIC,
        )
    if source_key == "hkie_cpd":
        return dict(
            baseline_html=_read(PRODUCTION_HKIE),
            drift_html=_read(HKIE_DRIFT),
            decoy_html=_read(HKIE_DECOY),
            url=HKIE_URL,
            css=CSS_HKIE_CARD,
            identifier=IDENT_HKIE_CARD,
            expected="Organizational Level Greenhouse Gas Accounting",
            prefer="Organizational Level Greenhouse Gas Accounting",
            state=STATE_HKIE,
        )
    if source_key == "hkgbc":
        return dict(
            baseline_html=_read(PRODUCTION_HKGBC),
            drift_html=_read(HKGBC_DRIFT),
            decoy_html=_read(HKGBC_DECOY),
            url=HKGBC_URL,
            css=CSS_HKGBC_CARD,
            identifier=IDENT_HKGBC_CARD,
            expected="IAMC",
            prefer="IAMC",
            state=STATE_HKGBC,
        )
    raise ValueError(source_key)


def evaluate_adaptive(source_key: str, persist_state: bool = True) -> Dict[str, Any]:
    cfg = _adaptive_pair(source_key)
    # Drift case: class renamed, intended event still present.
    drift = run_adaptive_case(
        baseline_html=cfg["baseline_html"],
        trial_html=cfg["drift_html"],
        url=cfg["url"],
        storage_file=cfg["state"] if persist_state else cfg["state"] + ".tmp",
        css=cfg["css"],
        identifier=cfg["identifier"],
        expected_text_contains=cfg["expected"],
        prefer_text_contains=cfg["prefer"],
    )
    # Decoy case: intended event removed; only a similar nav/sidebar remains.
    decoy = run_adaptive_case(
        baseline_html=cfg["baseline_html"],
        trial_html=cfg["decoy_html"],
        url=cfg["url"],
        storage_file=cfg["state"] if persist_state else cfg["state"] + ".tmp",
        css=cfg["css"],
        identifier=cfg["identifier"],
        expected_text_contains=cfg["expected"],
        prefer_text_contains=cfg["prefer"],
    )
    recoveries = failures = false_positives = 0
    for case in (drift, decoy):
        if case["status"] == AUTO_MATCH_RECOVERED:
            recoveries += 1
        elif case["status"] == AUTO_MATCH_FAILED:
            failures += 1
        elif case["status"] == AUTO_MATCH_FALSE_POSITIVE:
            false_positives += 1
    state_bytes = os.path.getsize(cfg["state"]) if os.path.isfile(cfg["state"]) else 0
    return {
        "drift": drift,
        "decoy": decoy,
        "adaptive_recoveries": recoveries,
        "adaptive_failures": failures,
        "adaptive_false_positives": false_positives,
        "state_bytes": state_bytes,
        "primary_status": drift["status"],
        "decoy_status": decoy["status"],
        "correct_event_on_drift": drift.get("correct_event"),
    }


def run_source(
    source_key: str,
    *,
    try_live: bool = True,
) -> Dict[str, Any]:
    cfg_html = {
        "cic": (PRODUCTION_CIC, CIC_URL, parse_cic_html, STATE_CIC),
        "hkie_cpd": (PRODUCTION_HKIE, HKIE_URL, parse_hkie_cpd_html, STATE_HKIE),
        "hkgbc": (PRODUCTION_HKGBC, HKGBC_URL, parse_hkgbc_html, STATE_HKGBC),
    }[source_key]
    fixture_path, base, parser, state = cfg_html
    html = _read(fixture_path)
    fetch_detail = _hkgbc_fetch_detail_from_fixtures() if source_key == "hkgbc" else None

    t0 = time.perf_counter()
    if source_key == "hkgbc":
        shadow = parser(html, base, storage_file=state, fetch_detail=fetch_detail)
    else:
        shadow = parser(html, base, storage_file=state)
    parse_ms = int((time.perf_counter() - t0) * 1000)
    prod = _production_events(source_key, html, base, fetch_detail=fetch_detail)
    comparison = pair_events(prod, shadow["events"])
    adaptive = evaluate_adaptive(source_key, persist_state=True)

    live_meta = {
        "attempted": False,
        "status": "fixture_only",
        "fetch_duration_ms": 0,
        "rendering_used": False,
    }
    live_comparison = None
    if try_live:
        live = _live_fetch(base)
        live_meta = {
            "attempted": True,
            "status": live["status"],
            "fetch_duration_ms": live["fetch_duration_ms"],
            "rendering_used": live["rendering_used"],
            "html_bytes": len(live["html"]) if live.get("html") else 0,
        }
        if live.get("ok") and live.get("html"):
            t1 = time.perf_counter()
            if source_key == "hkgbc":
                live_shadow = parser(live["html"], base, storage_file=state, fetch_detail=None)
            else:
                live_shadow = parser(live["html"], base, storage_file=state)
            live_parse_ms = int((time.perf_counter() - t1) * 1000)
            live_prod = _production_events(source_key, live["html"], base, fetch_detail=None)
            live_comparison = pair_events(live_prod, live_shadow["events"])
            live_comparison["parse_duration_ms"] = live_parse_ms
            live_comparison["shadow_count_live"] = len(live_shadow["events"])
            live_comparison["production_count_live"] = len(live_prod)

    extras = {}
    if source_key == "cic":
        extras = {
            "candidate_count": shadow.get("candidate_count"),
            "valid_title_count": shadow.get("valid_title_count"),
            "future_event_count": shadow.get("future_event_count"),
        }

    report = {
        **comparison,
        **extras,
        "adaptive_recoveries": adaptive["adaptive_recoveries"],
        "adaptive_failures": adaptive["adaptive_failures"],
        "adaptive_false_positives": adaptive["adaptive_false_positives"],
        "adaptive_drift_status": adaptive["primary_status"],
        "adaptive_decoy_status": adaptive["decoy_status"],
        "adaptive_correct_event_on_drift": adaptive["correct_event_on_drift"],
        "adaptive_drift_recovered_text": (adaptive["drift"].get("recovered_text") or "")[:240],
        "adaptive_decoy_recovered_text": (adaptive["decoy"].get("recovered_text") or "")[:240],
        "state_bytes": adaptive["state_bytes"],
        "fetch_duration_ms": live_meta.get("fetch_duration_ms") or 0,
        "parse_duration_ms": parse_ms,
        "rendering_used": False,
        "selector_strategy": shadow.get("selector_strategy"),
        "live": live_meta,
        "live_comparison": live_comparison,
        "input": "production_fixture",
    }
    return report


def run_pilot(try_live: bool = True, report_path: Optional[str] = SHADOW_REPORT) -> Dict[str, Any]:
    before = snapshot_production()
    build_all()
    t0 = time.perf_counter()
    sources = {}
    for key in ("cic", "hkie_cpd", "hkgbc"):
        sources[key] = run_source(key, try_live=try_live)
    total_s = round(time.perf_counter() - t0, 3)
    state_total = sum(
        os.path.getsize(p)
        for p in (STATE_CIC, STATE_HKIE, STATE_HKGBC)
        if os.path.isfile(p)
    )
    report = {
        "run_at": dt.datetime.now(HKT).isoformat(timespec="seconds"),
        "timezone": "Asia/Hong_Kong",
        "scrapling_version": _scrapling_version(),
        "total_duration": total_s,
        "persistent_state_bytes_total": state_total,
        "persistence_recommendation": (
            "A (checked-in source-specific JSON fingerprints) plus "
            "C (regenerate baseline from fixtures). Not B (Actions cache) as the "
            "primary mechanism, and not default SQLite in site-packages."
        ),
        "js_rendering": {
            "cic": "not required for fixture HTML; live HTTP may still be empty if the official page is JS-rendered (Playwright already used by production, not by this shadow pilot)",
            "hkie_cpd": "not required for the official fixture HTML (Elementor cards are present in the static response used by production tests)",
            "hkgbc": "not required for fixture HTML; production already notes listing timeouts from some cloud IPs",
        },
        "sources": sources,
        "notes": {
            "production_writes": "none — shadow never writes events.json or source_health.json",
            "adaptive_limitation": (
                "Scrapling auto_save stores the first element's fingerprint only; "
                "adaptive relocate recovers that intended node after class rename, "
                "it is not a drop-in replacement for listing every sibling card."
            ),
        },
    }
    if report_path:
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    assert_production_unchanged(before, "scrapling_shadow.run_pilot")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Experimental Scrapling shadow pilot")
    parser.add_argument("--no-live", action="store_true", help="Skip polite live HTTP fetches")
    parser.add_argument("--report", default=SHADOW_REPORT)
    parser.add_argument(
        "--observation-out",
        default="",
        help="Write a single-run observation record (never overwrites pilot-baseline.json)",
    )
    parser.add_argument(
        "--environment",
        default="local",
        choices=("local", "github-actions"),
        help="Where this run is executing (recorded in the observation snippet only)",
    )
    args = parser.parse_args(argv)
    report = run_pilot(try_live=not args.no_live, report_path=args.report)
    if args.observation_out:
        record = build_run_record(
            report,
            kind="observation",
            environment=args.environment,
            python_version=detect_python_version(),
            main_commit=detect_commit(),
            actions_runtime=None,
        )
        write_observation_run(args.observation_out, record)
        report["observation_record_written"] = args.observation_out
    print(json.dumps({k: report[k] for k in report if k != "sources"}, ensure_ascii=False, indent=2))
    for key, src in report["sources"].items():
        print(
            f"{key}: prod={src['production_count']} shadow={src['shadow_count']} "
            f"matched={src['matched_events']} titles={src['title_matches']} "
            f"drift={src['adaptive_drift_status']} decoy={src['adaptive_decoy_status']} "
            f"live={src['live']['status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
