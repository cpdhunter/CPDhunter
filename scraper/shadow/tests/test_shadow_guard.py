"""Guard: shadow code must not write events.json or source_health.json."""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRAPER = os.path.join(ROOT, "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

from scraper.shadow.build_fixtures import build_all  # noqa: E402
from scraper.shadow.observation import (  # noqa: E402
    PILOT_START,
    PILOT_START_COMMIT,
    write_observation_run,
)
from scraper.shadow.paths import (  # noqa: E402
    OBSERVATION_LOG,
    PILOT_BASELINE,
    PRODUCTION_CIC,
    PRODUCTION_EVENTS,
    PRODUCTION_HEALTH,
    REPO_ROOT,
    SHADOW_ROOT,
)
from scraper.shadow.safety import (  # noqa: E402
    assert_production_unchanged,
    shadow_source_mentions_forbidden_writes,
    snapshot_production,
)
from scraper.shadow.scrapling_cic import parse_cic_html  # noqa: E402
from scraper.shadow.scrapling_shadow import run_pilot  # noqa: E402


def test_static_scan_no_production_writes():
    hits = shadow_source_mentions_forbidden_writes(SHADOW_ROOT)
    assert hits == [], hits
    print("test_static_scan_no_production_writes OK")


def test_runtime_does_not_touch_catalog():
    assert os.path.isfile(PRODUCTION_EVENTS)
    before = snapshot_production()
    build_all()
    html = open(PRODUCTION_CIC, encoding="utf-8").read()
    with tempfile.TemporaryDirectory() as td:
        parse_cic_html(html, storage_file=os.path.join(td, "cic.json"))
        report = os.path.join(td, "scrapling-shadow.json")
        run_pilot(try_live=False, report_path=report)
        assert os.path.isfile(report)
    assert_production_unchanged(before, "guard")
    print("test_runtime_does_not_touch_catalog OK")



def _load_yaml_text():
    path = os.path.join(REPO_ROOT, ".github", "workflows", "scrapling-shadow.yml")
    assert os.path.isfile(path), "missing isolated shadow workflow"
    return path, open(path, encoding="utf-8").read()


def test_shadow_workflow_isolation():
    path, text = _load_yaml_text()
    assert "name: Scrapling Shadow Pilot" in text
    assert "group: scrapling-shadow" in text
    assert "group: cpd-update" not in text
    assert "contents: read" in text
    assert "contents: write" not in text
    assert "pages: write" not in text
    assert "id-token: write" not in text
    assert "issues: write" not in text
    assert "git commit" not in text
    assert "git push" not in text
    assert "git add" not in text
    assert "actions/deploy-pages" not in text
    assert "actions/upload-pages-artifact" not in text
    assert "actions/configure-pages" not in text
    assert "scrapling[fetchers]" not in text
    assert "playwright install" not in text
    assert 'cron: "0 23 * * *"' in text
    assert "workflow_dispatch:" in text
    assert "update.yml" not in text
    assert "permissions-shadow.txt" not in text  # typo guard; real file is requirements-shadow.txt
    assert "scraper/shadow/requirements-shadow.txt" in text
    assert "scraper/requirements.txt" in text
    assert 'python-version: "3.12"' in text
    assert "assert_production_frozen.py" in text
    assert "--observation-out" in text
    assert "actions/upload-artifact@" in text
    # Daily CPD workflow remains a separate file
    daily = os.path.join(REPO_ROOT, ".github", "workflows", "update.yml")
    assert os.path.isfile(daily)
    daily_text = open(daily, encoding="utf-8").read()
    assert "group: cpd-update" in daily_text
    assert path != daily
    print("test_shadow_workflow_isolation OK")


def test_observation_refuses_to_overwrite_baseline():
    before = snapshot_production()
    try:
        write_observation_run(PILOT_BASELINE, {"record_type": "should-not-write"})
    except ValueError as exc:
        assert "pilot-baseline.json" in str(exc)
    else:
        raise AssertionError("write_observation_run must refuse pilot-baseline.json")
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "observation-run.json")
        write_observation_run(out, {"record_type": "observation", "ok": True})
        assert os.path.isfile(out)
    assert_production_unchanged(before, "observation-write")
    print("test_observation_refuses_to_overwrite_baseline OK")


def test_committed_baseline_and_log():
    import json

    assert os.path.isfile(PILOT_BASELINE), "pilot-baseline.json must be committed"
    assert os.path.isfile(OBSERVATION_LOG), "observation-log.json must be committed"
    baseline = json.loads(open(PILOT_BASELINE, encoding="utf-8").read())
    log = json.loads(open(OBSERVATION_LOG, encoding="utf-8").read())
    assert baseline["pilot_start"] == PILOT_START
    assert baseline["observation_period_start"] == "2026-11-16"
    assert baseline["current_main_commit_at_pilot_start"] == PILOT_START_COMMIT
    assert baseline["scrapling_version"] == "0.5.1"
    assert baseline["python"]["actions"] == "3.12"
    assert baseline["python"]["local_first_run"] == "3.13.5"
    wf = baseline["shadow_workflow"]
    assert wf["file"] == ".github/workflows/scrapling-shadow.yml"
    assert wf["concurrency_group"] == "scrapling-shadow"
    assert wf["permissions"] == {"contents": "read"}
    assert wf["commits"] is False
    assert wf["pages_deploy"] is False
    assert wf["writes_events_json"] is False
    assert wf["writes_source_health_json"] is False
    prod = baseline["production"]
    assert prod["events_json_sha256"] == "cc710062b7fe8606701f2e4512f8872e39932cde0af56c13de81d7e0ea4e4b09"
    assert prod["source_health_json_sha256"] == "8fb0a7136b8a7c53e25bdd4496e6eacc3105378be4e2e7cb6949302557e0697c"
    assert prod["events_json_updated"] == "2026-11-16T06:44+08:00"
    first = baseline["first_run"]
    assert first["run_at"] == PILOT_START
    assert first["environment"] == "local"
    assert first["workflow_runtime_seconds"] == 25.684
    assert first["actions_runtime"] is None
    cic = first["sources"]["cic"]
    assert cic["production_catalog"]["catalog_total"] == 6
    assert cic["production_catalog"]["catalog_future"] == 5
    assert cic["production_catalog"]["catalog_future_timed"] == 0
    assert cic["production_scrape_same_day"]["last_n"] == 0
    assert cic["production_scrape_same_day"]["last_status"] == "EMPTY_UNVERIFIED"
    assert cic["shadow_fixture"]["production_count"] == 1
    assert cic["shadow_fixture"]["shadow_count"] == 1
    assert cic["shadow_fixture"]["matched_events"] == 1
    assert cic["shadow_live"]["production_count"] == 0
    assert cic["shadow_live"]["shadow_count"] == 0
    assert cic["adaptive"]["drift"] == "AUTO_MATCH_RECOVERED"
    assert cic["adaptive"]["decoy"] == "AUTO_MATCH_FALSE_POSITIVE"
    hkie = first["sources"]["hkie_cpd"]
    assert hkie["production_catalog"]["catalog_total"] == 15
    assert hkie["production_catalog"]["catalog_future"] == 15
    assert hkie["production_catalog"]["catalog_future_timed"] == 7
    assert hkie["production_scrape_same_day"]["last_n"] == 10
    assert hkie["shadow_fixture"]["matched_events"] == 10
    assert hkie["shadow_live"]["matched_events"] == 10
    assert hkie["adaptive"]["drift"] == "AUTO_MATCH_RECOVERED"
    assert hkie["adaptive"]["decoy"] == "AUTO_MATCH_FAILED"
    hkgbc = first["sources"]["hkgbc"]
    assert hkgbc["production_catalog"]["catalog_total"] == 26
    assert hkgbc["production_catalog"]["catalog_future"] == 24
    assert hkgbc["production_catalog"]["catalog_future_timed"] == 0
    assert hkgbc["production_scrape_same_day"]["last_n"] == 24
    assert hkgbc["shadow_fixture"]["matched_events"] == 7
    assert hkgbc["shadow_live"]["production_count"] == 40
    assert hkgbc["shadow_live"]["shadow_count"] == 942
    assert hkgbc["shadow_live"]["matched_events"] == 40
    assert hkgbc["shadow_live"]["shadow_only"] == 902
    assert hkgbc["shadow_live"]["suspected_false_positives"] == 902
    assert hkgbc["shadow_live"]["confirmed_shadow_false_positives"] == 0
    assert hkgbc["adaptive"]["drift"] == "AUTO_MATCH_FALSE_POSITIVE"
    assert hkgbc["adaptive"]["decoy"] == "AUTO_MATCH_FALSE_POSITIVE"
    assert log["pilot_start"] == PILOT_START
    assert log["append_only"] is True
    assert len(log["runs"]) == 1
    assert log["runs"][0]["run_at"] == PILOT_START
    print("test_committed_baseline_and_log OK")


if __name__ == "__main__":
    test_static_scan_no_production_writes()
    test_runtime_does_not_touch_catalog()
    test_shadow_workflow_isolation()
    test_observation_refuses_to_overwrite_baseline()
    test_committed_baseline_and_log()
    print("guard tests passed")
