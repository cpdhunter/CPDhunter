"""Read-only observation records for the Scrapling shadow pilot.

This module never writes events.json, source_health.json, or
pilot-baseline.json. Scheduled runs should write a per-run snippet to
observation-run.json (uploaded as an Actions artifact, not committed).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional

from .paths import (
    OBSERVATION_RUN,
    PILOT_SOURCE_LABELS,
    PRODUCTION_EVENTS,
    PRODUCTION_HEALTH,
    REPO_ROOT,
)

HKT = dt.timezone(dt.timedelta(hours=8))

SCHEMA_RUN = "scrapling-shadow-observation/v1"
SCHEMA_BASELINE = "scrapling-shadow-pilot-baseline/v1"
SCHEMA_LOG = "scrapling-shadow-observation-log/v1"

PILOT_START = "2026-11-16T09:13:50+08:00"
OBSERVATION_PERIOD_START = "2026-11-16"
PILOT_START_COMMIT = "582a77958b57643a7a18387eb323de756bd82f40"

COMPARISON_FIELDS = (
    "production_count",
    "shadow_count",
    "matched_events",
    "production_only",
    "shadow_only",
    "title_matches",
    "title_mismatches",
    "date_matches",
    "date_mismatches",
    "url_matches",
    "false_positive_candidates",
)

WORKFLOW_CONFIG = {
    "file": ".github/workflows/scrapling-shadow.yml",
    "name": "Scrapling Shadow Pilot",
    "triggers": ["schedule", "workflow_dispatch"],
    "schedule_cron_utc": "0 23 * * *",
    "schedule_note": (
        "07:00 HKT every day, after Daily CPD at 0 22 * * * UTC (06:00 HKT), "
        "so same-date events.json on main can be compared."
    ),
    "permissions": {"contents": "read"},
    "concurrency_group": "scrapling-shadow",
    "does_not_share_daily_cpd_concurrency": True,
    "commits": False,
    "pages_deploy": False,
    "writes_events_json": False,
    "writes_source_health_json": False,
    "installs_scrapling_fetchers": False,
    "isolated_from_daily_cpd": True,
    "actions_runtime_at_baseline": None,
    "actions_runtime_note": (
        "First run was local (~25.684s total). Actions runtime is N/A "
        "until the first workflow run."
    ),
}


def sha256_file(path: str) -> str:
    if not os.path.isfile(path):
        return "MISSING"
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_commit() -> str:
    sha = os.environ.get("GITHUB_SHA") or os.environ.get("GIT_COMMIT")
    if sha:
        return sha
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def detect_python_version() -> str:
    return sys.version.split()[0]


def _as_of_hkt(now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.now(HKT)
    return now.date().isoformat()


def _is_timed(event: Dict[str, Any]) -> bool:
    return bool((event.get("time") or "").strip())


def catalog_snapshot(
    events_path: str = PRODUCTION_EVENTS,
    health_path: str = PRODUCTION_HEALTH,
    as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Read-only snapshot of production catalog + health for the three pilot sources."""
    as_of = as_of or _as_of_hkt()
    with open(events_path, encoding="utf-8") as fh:
        events_doc = json.load(fh)
    with open(health_path, encoding="utf-8") as fh:
        health = json.load(fh)
    evs = events_doc.get("events") or []
    result: Dict[str, Any] = {
        "events_updated": events_doc.get("updated"),
        "events_total": len(evs),
        "events_future": sum(1 for e in evs if (e.get("date") or "") >= as_of),
        "as_of": as_of,
        "sources": {},
    }
    for key, name in PILOT_SOURCE_LABELS.items():
        subset = [e for e in evs if e.get("source") == name]
        future = [e for e in subset if (e.get("date") or "") >= as_of]
        h = health.get(name) or {}
        result["sources"][key] = {
            "source_name": name,
            "catalog_total": len(subset),
            "catalog_future": len(future),
            "catalog_future_timed": sum(1 for e in future if _is_timed(e)),
            "source_health": {
                "last_status": h.get("last_status"),
                "last_n": h.get("last_n"),
                "last_method": h.get("last_method"),
                "last_error": h.get("last_error"),
                "raw_candidates": h.get("raw_candidates"),
                "rejects": h.get("rejects"),
                "consecutive_fail": h.get("consecutive_fail"),
                "last_success": h.get("last_success"),
                "updated": h.get("updated"),
            },
        }
    return result


def accuracy(matches: int, denominator: int) -> Dict[str, Any]:
    if not denominator:
        return {
            "matches": matches,
            "denominator": denominator,
            "ratio": None,
            "label": "n/a (denominator zero)",
        }
    return {
        "matches": matches,
        "denominator": denominator,
        "ratio": round(matches / denominator, 4),
        "label": f"{matches}/{denominator}",
    }


def comparison_view(
    block: Optional[Dict[str, Any]],
    *,
    suspected_note: Optional[str] = None,
) -> Dict[str, Any]:
    block = block or {}
    view = {k: block.get(k) for k in COMPARISON_FIELDS}
    suspected = int(block.get("false_positive_candidates") or 0)
    view["suspected_false_positives"] = suspected
    # A candidate is not a confirmed false positive until reviewed.
    view["confirmed_shadow_false_positives"] = 0
    view["confirmed_production_misses"] = 0
    if suspected_note:
        view["suspected_false_positives_note"] = suspected_note
    prod_n = int(block.get("production_count") or 0)
    view["title_accuracy"] = accuracy(int(block.get("title_matches") or 0), prod_n)
    view["date_accuracy"] = accuracy(int(block.get("date_matches") or 0), prod_n)
    view["url_accuracy"] = accuracy(int(block.get("url_matches") or 0), prod_n)
    return view


def _hkgbc_live_note(live: Dict[str, Any]) -> Optional[str]:
    shadow_only = int(live.get("shadow_only") or 0)
    prod_n = int(live.get("production_count") or 0)
    if shadow_only <= 0:
        return None
    return (
        f"Live HKGBC over-extracted {shadow_only} extra unique title+date "
        f"candidates vs production cap {prod_n} — suspected false positives, "
        "not confirmed until reviewed."
    )


def _cic_health_note(health: Dict[str, Any]) -> Optional[str]:
    if health.get("last_n") == 0:
        return (
            "Today's production scrape got 0 events (JS-rendered listing; "
            "shadow live also 0)."
        )
    return None


def build_source_observation(
    key: str,
    src: Dict[str, Any],
    catalog_source: Dict[str, Any],
    as_of: str,
) -> Dict[str, Any]:
    live = src.get("live_comparison") or {}
    live_meta = src.get("live") or {}
    health = catalog_source.get("source_health") or {}
    live_note = _hkgbc_live_note(live) if key == "hkgbc" else None
    scrape = dict(health)
    cic_note = _cic_health_note(health) if key == "cic" else None
    if cic_note:
        scrape["note"] = cic_note
    shadow_live: Dict[str, Any]
    if live_meta.get("attempted"):
        shadow_live = comparison_view(live, suspected_note=live_note)
        shadow_live.update(
            {
                "attempted": True,
                "status": live_meta.get("status"),
                "fetch_duration_ms": live_meta.get("fetch_duration_ms"),
                "parse_duration_ms": live.get("parse_duration_ms"),
                "browser_rendering_used": bool(
                    live_meta.get("rendering_used") or src.get("rendering_used")
                ),
                "html_bytes": live_meta.get("html_bytes"),
            }
        )
    else:
        shadow_live = {"attempted": False, "status": live_meta.get("status") or "fixture_only"}
    return {
        "production_catalog": {
            "source_name": catalog_source.get("source_name"),
            "catalog_total": catalog_source.get("catalog_total"),
            "catalog_future": catalog_source.get("catalog_future"),
            "catalog_future_timed": catalog_source.get("catalog_future_timed"),
            "as_of": as_of,
        },
        "production_scrape_same_day": scrape,
        "shadow_fixture": comparison_view(src),
        "shadow_live": shadow_live,
        "adaptive": {
            "drift": src.get("adaptive_drift_status"),
            "decoy": src.get("adaptive_decoy_status"),
            "recoveries": src.get("adaptive_recoveries"),
            "failures": src.get("adaptive_failures"),
            "false_positives": src.get("adaptive_false_positives"),
            "correct_event_on_drift": src.get("adaptive_correct_event_on_drift"),
            "drift_recovered_text": src.get("adaptive_drift_recovered_text"),
            "decoy_recovered_text": src.get("adaptive_decoy_recovered_text"),
        },
        "timings": {
            "fetch_duration_ms": src.get("fetch_duration_ms"),
            "parse_duration_ms": src.get("parse_duration_ms"),
            "browser_rendering_used": bool(src.get("rendering_used")),
        },
        "selector_strategy": src.get("selector_strategy"),
    }


def build_run_record(
    report: Dict[str, Any],
    *,
    kind: str = "observation",
    environment: str = "local",
    python_version: Optional[str] = None,
    main_commit: Optional[str] = None,
    actions_runtime: Any = None,
    catalog: Optional[Dict[str, Any]] = None,
    as_of: Optional[str] = None,
) -> Dict[str, Any]:
    as_of = as_of or _as_of_hkt()
    catalog = catalog or catalog_snapshot(as_of=as_of)
    sources_out = {}
    for key in ("cic", "hkie_cpd", "hkgbc"):
        sources_out[key] = build_source_observation(
            key,
            (report.get("sources") or {}).get(key) or {},
            (catalog.get("sources") or {}).get(key) or {},
            as_of,
        )
    return {
        "record_type": kind,
        "schema": SCHEMA_RUN,
        "run_at": report.get("run_at"),
        "timezone": report.get("timezone") or "Asia/Hong_Kong",
        "kind": kind,
        "environment": environment,
        "python_version": python_version or detect_python_version(),
        "python_actions": "3.12",
        "scrapling_version": report.get("scrapling_version"),
        "main_commit": main_commit or detect_commit(),
        "workflow_runtime_seconds": report.get("total_duration"),
        "actions_runtime": actions_runtime,
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "production": {
            "events_json_sha256": sha256_file(PRODUCTION_EVENTS),
            "source_health_json_sha256": sha256_file(PRODUCTION_HEALTH),
            "events_json_updated": catalog.get("events_updated"),
            "events_total": catalog.get("events_total"),
            "events_future": catalog.get("events_future"),
            "events_future_as_of": catalog.get("as_of"),
        },
        "sources": sources_out,
    }


def build_pilot_baseline(report: Dict[str, Any], run_record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "record_type": "pilot_baseline",
        "schema": SCHEMA_BASELINE,
        "pilot_start": PILOT_START,
        "observation_period_start": OBSERVATION_PERIOD_START,
        "minimum_observation_days": 7,
        "preferred_observation_days": 14,
        "recorded_at": dt.datetime.now(HKT).isoformat(timespec="seconds"),
        "current_main_commit_at_pilot_start": PILOT_START_COMMIT,
        "scrapling_version": report.get("scrapling_version") or "0.5.1",
        "python": {
            "actions": "3.12",
            "local_first_run": "3.13.5",
            "note": (
                "First shadow run was local on CPython 3.13.5. Production CI / "
                "Daily CPD and the isolated Scrapling Shadow workflow use 3.12."
            ),
        },
        "shadow_workflow": WORKFLOW_CONFIG,
        "production": run_record.get("production"),
        "workflow_runtime": {
            "local_first_run_seconds": report.get("total_duration"),
            "actions_runtime": None,
            "note": (
                "First run was local, 25.684s total. Actions runtime is N/A "
                "until the first workflow run."
            ),
        },
        "first_run_artifact": "scraper/shadow/artifacts/scrapling-shadow.json",
        "observation_log": "scraper/shadow/artifacts/observation-log.json",
        "first_run": run_record,
        "honest_assessment": report.get("honest_assessment"),
        "notes": {
            "production_writes": "none — shadow never writes events.json or source_health.json",
            "live_observations": (report.get("notes") or {}).get("live_observations"),
            "adaptive_limitation": (report.get("notes") or {}).get("adaptive_limitation"),
            "migration": "Do not migrate Scrapling into production during the observation period.",
        },
    }


def build_observation_log(run_record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_LOG,
        "pilot_start": PILOT_START,
        "observation_period_start": OBSERVATION_PERIOD_START,
        "minimum_days": 7,
        "preferred_days": 14,
        "append_only": True,
        "note": (
            "Committed log holds the baseline run only. Scheduled workflow runs "
            "upload a per-run observation snippet as an Actions artifact and "
            "must not commit this file."
        ),
        "runs": [run_record],
    }


def write_json(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_observation_run(path: str, record: Dict[str, Any]) -> None:
    """Write a single-run snippet. Never write pilot-baseline.json."""
    resolved = os.path.abspath(path)
    if os.path.basename(resolved) == "pilot-baseline.json":
        raise ValueError("refusing to overwrite pilot-baseline.json")
    write_json(path or OBSERVATION_RUN, record)
