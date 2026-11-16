"""Adaptive DOM-drift recover / fail / false-positive cases for all three sources.

A recovered wrong element is reported as AUTO_MATCH_FALSE_POSITIVE and is
treated as worse than AUTO_MATCH_FAILED. Tests lock in the observed honest
results so a later change cannot silently flip a false positive to a 'pass'.
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRAPER = os.path.join(ROOT, "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

from scraper.shadow.adaptive import (  # noqa: E402
    AUTO_MATCH_FAILED,
    AUTO_MATCH_FALSE_POSITIVE,
    AUTO_MATCH_RECOVERED,
    run_adaptive_case,
)
from scraper.shadow.build_fixtures import build_all  # noqa: E402
from scraper.shadow.paths import (  # noqa: E402
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
    PRODUCTION_HKIE,
)


def _read(path):
    return open(path, encoding="utf-8").read()


CASES = {
    "cic": dict(
        baseline=PRODUCTION_CIC,
        drift=CIC_DRIFT,
        decoy=CIC_DECOY,
        url=CIC_URL,
        css=CSS_CIC_CARD,
        ident=IDENT_CIC_CARD,
        expected="Temporary Works Workshop 2026",
        drift_status=AUTO_MATCH_RECOVERED,
        decoy_status=AUTO_MATCH_FALSE_POSITIVE,  # article-like sidebar is a realistic false positive
    ),
    "hkie_cpd": dict(
        baseline=PRODUCTION_HKIE,
        drift=HKIE_DRIFT,
        decoy=HKIE_DECOY,
        url=HKIE_URL,
        css=CSS_HKIE_CARD,
        ident=IDENT_HKIE_CARD,
        expected="Organizational Level Greenhouse Gas Accounting",
        drift_status=AUTO_MATCH_RECOVERED,
        decoy_status=AUTO_MATCH_FAILED,
    ),
    "hkgbc": dict(
        baseline=PRODUCTION_HKGBC,
        drift=HKGBC_DRIFT,
        decoy=HKGBC_DECOY,
        url=HKGBC_URL,
        css=CSS_HKGBC_CARD,
        ident=IDENT_HKGBC_CARD,
        expected="IAMC",
        # Intended IAMC card is saved, but relocate returns a different similar event card
        # (badge-only "Supporting Event" row) — a false positive, worse than failure.
        drift_status=AUTO_MATCH_FALSE_POSITIVE,
        decoy_status=AUTO_MATCH_FALSE_POSITIVE,
    ),
}


def _run(source, kind):
    cfg = CASES[source]
    trial = cfg["drift"] if kind == "drift" else cfg["decoy"]
    with tempfile.TemporaryDirectory() as td:
        state = os.path.join(td, f"{source}.json")
        return run_adaptive_case(
            baseline_html=_read(cfg["baseline"]),
            trial_html=_read(trial),
            url=cfg["url"],
            storage_file=state,
            css=cfg["css"],
            identifier=cfg["ident"],
            expected_text_contains=cfg["expected"],
            prefer_text_contains=cfg["expected"],
        )


def test_adaptive_drift_and_decoy():
    build_all()
    results = {}
    for source, cfg in CASES.items():
        drift = _run(source, "drift")
        decoy = _run(source, "decoy")
        results[source] = {"drift": drift, "decoy": decoy}
        assert drift["original_selector_failed"], (source, "drift: original CSS should miss", drift)
        assert decoy["original_selector_failed"], (source, "decoy: original CSS should miss", decoy)
        assert drift["status"] == cfg["drift_status"], (source, "drift", drift)
        assert decoy["status"] == cfg["decoy_status"], (source, "decoy", decoy)
        if cfg["drift_status"] == AUTO_MATCH_RECOVERED:
            assert drift["correct_event"] is True, (source, drift["recovered_text"])
        else:
            assert drift["correct_event"] is False
        if cfg["decoy_status"] == AUTO_MATCH_FALSE_POSITIVE:
            assert decoy["adaptive_count"] >= 1
            assert decoy["correct_event"] is False
        print(
            f"adaptive {source}: drift={drift['status']} (correct={drift['correct_event']}) "
            f"decoy={decoy['status']}"
        )
    return results


if __name__ == "__main__":
    test_adaptive_drift_and_decoy()
    print("adaptive tests passed")
