"""Run all Scrapling shadow-pilot tests. Usage: python scraper/shadow/tests/run_tests.py"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_adaptive import test_adaptive_drift_and_decoy  # noqa: E402
from test_shadow_cic import test_cic_titles_from_fixture  # noqa: E402
from test_shadow_guard import (  # noqa: E402
    test_runtime_does_not_touch_catalog,
    test_static_scan_no_production_writes,
)
from test_shadow_hkgbc import test_hkgbc_rejects_badges_and_keeps_titles  # noqa: E402
from test_shadow_hkie_cpd import test_hkie_card_scope_pairs  # noqa: E402


def main() -> int:
    test_cic_titles_from_fixture()
    test_hkie_card_scope_pairs()
    test_hkgbc_rejects_badges_and_keeps_titles()
    test_adaptive_drift_and_decoy()
    test_static_scan_no_production_writes()
    test_runtime_does_not_touch_catalog()
    print("All Scrapling shadow tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
