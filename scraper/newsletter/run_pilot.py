#!/usr/bin/env python3
"""CIC i-Club newsletter discovery pilot runner.

Reads sanitized .eml / HTML / text fixtures only. Never opens a mailbox,
never writes events.json or source_health.json, never POSTs, never
registers, and never fetches tracking pixels or remote email images.

Usage (from repo root):
  python scraper/newsletter/run_pilot.py
  python scraper/newsletter/run_pilot.py --offline --fixtures scraper/newsletter/fixtures
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRAPER = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRAPER)
if _SCRAPER not in sys.path:
    sys.path.insert(0, _SCRAPER)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from newsletter.cic_iclub import (
    PassiveHttp,
    process_newsletter,
)
from newsletter.normalize import (
    DISCOVERY,
    ORGANISATION,
    SOURCE_NAME,
    STATUS_ELIGIBLE,
    STATUS_REJECTED,
    STATUS_REVIEW,
    canonical_registration_url,
    public_candidate_view,
)

EVENTS_JSON = os.path.join(_ROOT, "events.json")
HEALTH_JSON = os.path.join(_ROOT, "source_health.json")
DEFAULT_FIXTURES = os.path.join(_HERE, "fixtures")
DEFAULT_REPORT = os.path.join(_HERE, "artifacts", "pilot-report.json")
DEST_MAP_PATH = os.path.join(DEFAULT_FIXTURES, "destination_map.json")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_production() -> Dict[str, Any]:
    out = {}
    for path in (EVENTS_JSON, HEALTH_JSON):
        out[path] = {
            "exists": os.path.isfile(path),
            "sha256": sha256_file(path) if os.path.isfile(path) else None,
            "mtime": os.path.getmtime(path) if os.path.isfile(path) else None,
            "size": os.path.getsize(path) if os.path.isfile(path) else 0,
        }
    return out


def assert_production_unchanged(before: Dict[str, Any]) -> None:
    after = snapshot_production()
    mismatches = []
    for path in (EVENTS_JSON, HEALTH_JSON):
        if before.get(path, {}).get("sha256") != after.get(path, {}).get("sha256"):
            mismatches.append(
                f"{path}: {before.get(path, {}).get('sha256')} -> {after.get(path, {}).get('sha256')}"
            )
    if mismatches:
        raise SystemExit(
            "pilot wrote or modified production catalogues (forbidden):\n  "
            + "\n  ".join(mismatches)
        )


def load_production_events() -> List[Dict[str, Any]]:
    if not os.path.isfile(EVENTS_JSON):
        return []
    with open(EVENTS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events") if isinstance(data, dict) else data
    return events if isinstance(events, list) else []


def load_destination_map(fixtures_dir: str) -> Dict[str, str]:
    """Map registration URL → sanitized destination HTML (offline verification)."""
    path = os.path.join(fixtures_dir, "destination_map.json")
    if not os.path.isfile(path):
        path = DEST_MAP_PATH
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out: Dict[str, str] = {}
    for url, rel in (raw or {}).items():
        html_path = rel if os.path.isabs(rel) else os.path.join(fixtures_dir, rel)
        if os.path.isfile(html_path):
            out[url] = open(html_path, encoding="utf-8").read()
    return out


def list_newsletter_fixtures(fixtures_dir: str) -> List[str]:
    paths = []
    if not os.path.isdir(fixtures_dir):
        return paths
    for name in sorted(os.listdir(fixtures_dir)):
        if name.startswith("."):
            continue
        path = os.path.join(fixtures_dir, name)
        if not os.path.isfile(path):
            continue
        if name.lower().endswith((".eml", ".html", ".htm", ".txt")):
            paths.append(path)
    return paths


def is_synthetic_fixture(fixture_name: str, candidate: Dict[str, Any]) -> bool:
    """Test-only fixtures must not count as real i-Club coverage."""
    name = (fixture_name or "").lower()
    dest = (candidate.get("registration_destination") or "").lower()
    title = (candidate.get("title") or "")
    if "malformed" in name:
        return True
    if "wn_pilot" in dest or "page-pilot-" in dest or "pilot-" in dest:
        return True
    if "pilot" in name and "life_first" not in name:
        return True
    # Known synthetic / constructed test messages
    if name in {
        "trusted_future_webinar.eml",
        "untrusted_forward.eml",
        "chinese_title_date.eml",
        "zoom_meeting_register.eml",
        "zoom_join_only.eml",
        "online_registration_only.eml",
        "explicit_cpd_hours.eml",
        "estimated_duration.eml",
        "closed_registration.eml",
        "tracking_and_pii.eml",
        "uncertain_no_date.eml",
        "generic_occupational_health.eml",
        "paid_event.eml",
    }:
        return True
    return False


def recommend(summary: Dict[str, Any]) -> str:
    """Mailbox ingestion stays out of scope until real newsletters show coverage.

    Synthetic test fixtures can be PRODUCTION_ELIGIBLE; they do not prove that
    live i-Club mail would add unique future events to the catalogue.
    """
    if summary.get("pii_retained") or summary.get("network_post") or summary.get("production_affected"):
        return "NO_GO"
    real_unique_future = summary.get("real_unique_newsletter_only_future_eligible") or 0
    if real_unique_future >= 1:
        return "GO_TO_MAILBOX_INGESTION_DESIGN"
    return "MORE_FIXTURES"


def run_pilot(
    fixtures_dir: str = DEFAULT_FIXTURES,
    *,
    verify: bool = False,
    production_events: Optional[List[Dict[str, Any]]] = None,
    report_path: Optional[str] = None,
    http: Optional[PassiveHttp] = None,
) -> Dict[str, Any]:
    before = snapshot_production()
    events = production_events if production_events is not None else load_production_events()
    dest_map = load_destination_map(fixtures_dir)
    http = http or PassiveHttp()
    messages = list_newsletter_fixtures(fixtures_dir)
    results = []
    candidates_out = []

    for path in messages:
        raw = open(path, "rb").read()
        # Envelope From is inside .eml; saved html/txt from the official
        # fixture set may be marked trusted only when a sidecar says so.
        trusted_html = False
        sidecar = path + ".meta.json"
        from_header = None
        if os.path.isfile(sidecar):
            meta = json.loads(open(sidecar, encoding="utf-8").read())
            from_header = meta.get("from")
            trusted_html = bool(meta.get("trusted_html"))
        rec = process_newsletter(
            raw,
            from_header=from_header,
            production_events=events,
            http=http if verify else None,
            destination_map=dest_map,
            verify=verify,
            trusted_html=trusted_html,
        )
        views = [public_candidate_view(c) for c in rec.get("candidates") or []]
        results.append({
            "fixture": os.path.relpath(path, fixtures_dir),
            "trusted": rec.get("trusted"),
            "sender_domain": rec.get("sender_domain"),
            "malformed": rec.get("malformed"),
            "pii_leaks": rec.get("pii_leaks") or [],
            "candidates": views,
        })
        candidates_out.extend(views)

    posts = list(http.posts)
    pii_hits = [r["pii_leaks"] for r in results if r["pii_leaks"]]
    valid_future = [
        c for c in candidates_out
        if c.get("date") and "C" not in (c.get("gate_failures") or [])
    ]
    eligible = [c for c in candidates_out if c.get("pilot_status") == STATUS_ELIGIBLE]
    review = [c for c in candidates_out if c.get("pilot_status") == STATUS_REVIEW]
    rejected = [c for c in candidates_out if c.get("pilot_status") == STATUS_REJECTED]
    dups = [c for c in candidates_out if c.get("duplicate_status") == "duplicate"]
    unique = [c for c in candidates_out if c.get("duplicate_status") == "unique_newsletter_only"]
    unique_future_eligible = [
        c for c in unique
        if c.get("pilot_status") == STATUS_ELIGIBLE
    ]
    # Pair candidates back to fixtures for synthetic vs real coverage.
    real_unique_future_eligible = []
    for msg in results:
        fixture = msg.get("fixture") or ""
        for c in msg.get("candidates") or []:
            if (
                c.get("duplicate_status") == "unique_newsletter_only"
                and c.get("pilot_status") == STATUS_ELIGIBLE
                and not is_synthetic_fixture(fixture, c)
            ):
                real_unique_future_eligible.append(c)
    zoom_webinar = [c for c in candidates_out if c.get("registration_mechanism") == "ZOOM_WEBINAR"]
    gforms = [c for c in candidates_out if c.get("registration_mechanism") == "GOOGLE_FORMS"]
    other_reg = [
        c for c in candidates_out
        if c.get("registration_mechanism")
        and c.get("registration_mechanism") not in ("ZOOM_WEBINAR", "GOOGLE_FORMS")
    ]
    closed = [c for c in candidates_out if c.get("registration_status") == "CLOSED" or c.get("cancelled")]
    hs = [c for c in candidates_out if c.get("type") == "H&S"]
    civil = [c for c in candidates_out if c.get("civil_related")]

    after = snapshot_production()
    production_affected = any(
        before[p]["sha256"] != after[p]["sha256"] for p in before
    )
    summary = {
        "newsletter_messages": len(messages),
        "candidate_events": len(candidates_out),
        "valid_future_events": len(valid_future),
        "production_eligible": len(eligible),
        "review": len(review),
        "rejected": len(rejected),
        "duplicates_against_current_events": len(dups),
        "unique_newsletter_only_events": len(unique),
        "unique_newsletter_only_future_eligible": len(unique_future_eligible),
        "real_unique_newsletter_only_future_eligible": len(real_unique_future_eligible),
        "zoom_webinar_destinations": len(zoom_webinar),
        "google_forms": len(gforms),
        "other_registrations": len(other_reg),
        "closed": len(closed),
        "h_and_s_events": len(hs),
        "civil_construction_related_events": len(civil),
        "events_json_unchanged": before[EVENTS_JSON]["sha256"] == after[EVENTS_JSON]["sha256"],
        "source_health_unchanged": before[HEALTH_JSON]["sha256"] == after[HEALTH_JSON]["sha256"],
        "events_json_sha256": after[EVENTS_JSON]["sha256"],
        "source_health_sha256": after[HEALTH_JSON]["sha256"],
        "pii_retained": bool(pii_hits),
        "network_post": bool(posts),
        "production_affected": production_affected,
        "http_gets": list(http.gets),
        "http_posts": posts,
    }
    summary["recommendation"] = recommend(summary)

    report = {
        "pilot": "CIC i-Club newsletter discovery",
        "discovery": DISCOVERY,
        "source": SOURCE_NAME,
        "organisation": ORGANISATION,
        "trusted_sender_rule": {
            "allowlist_domains": ["cic.hk", "cic.org.hk"],
            "subdomains_allowed": True,
            "arbitrary_forwards_authoritative": False,
            "provenance_emitted": ["discovery", "source", "organisation", "sender_domain"],
        },
        "summary": summary,
        "candidates": candidates_out,
        "messages": results,
    }

    if report_path:
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")

    assert_production_unchanged(before)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CIC i-Club newsletter discovery pilot")
    parser.add_argument("--fixtures", default=DEFAULT_FIXTURES, help="Directory of sanitized .eml/.html/.txt fixtures")
    parser.add_argument("--report", default=DEFAULT_REPORT, help="Write JSON report here (not events.json)")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Passively GET public registration destinations (never POST)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not GET the network; use sanitized destination fixtures only (default)",
    )
    args = parser.parse_args(argv)
    verify = bool(args.verify) and not args.offline
    report = run_pilot(
        args.fixtures,
        verify=verify,
        report_path=args.report,
    )
    s = report["summary"]
    print("CIC i-Club newsletter discovery pilot")
    print(f"  messages={s['newsletter_messages']} candidates={s['candidate_events']}")
    print(f"  valid_future={s['valid_future_events']} eligible={s['production_eligible']} review={s['review']} rejected={s['rejected']}")
    print(f"  duplicates={s['duplicates_against_current_events']} unique={s['unique_newsletter_only_events']}")
    print(f"  zoom_webinar={s['zoom_webinar_destinations']} gforms={s['google_forms']} other_reg={s['other_registrations']} closed={s['closed']}")
    print(f"  events.json unchanged: {'YES' if s['events_json_unchanged'] else 'NO'} sha256={s['events_json_sha256']}")
    print(f"  source_health unchanged: {'YES' if s['source_health_unchanged'] else 'NO'} sha256={s['source_health_sha256']}")
    print(f"  PII retained: {'YES' if s['pii_retained'] else 'NO'}")
    print(f"  network POST: {'YES' if s['network_post'] else 'NO'}")
    print(f"  production affected: {'YES' if s['production_affected'] else 'NO'}")
    print(f"  recommendation: {s['recommendation']}")
    if args.report:
        print(f"  report: {args.report}")
    for c in report["candidates"]:
        print(
            f"  - {c.get('pilot_status')} | {c.get('title')} | date={c.get('date')} "
            f"time={c.get('time') or '-'} mode={c.get('mode')} type={c.get('type')} "
            f"civil={c.get('civil_related')} hrs={c.get('hrs')} est={c.get('hrs_est')} "
            f"free={c.get('free')} mech={c.get('registration_mechanism')} "
            f"reg={c.get('registration_status')} dup={c.get('duplicate_status')} "
            f"conf={c.get('confidence')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
