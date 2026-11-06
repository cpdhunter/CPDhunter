"""Minimal parser smoke tests. Run: python scraper/test_parsers.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from fetch import parse_date, classify_rule

def test_parse_date():
    assert parse_date("9-11 Dec 2026") == "2026-12-09"
    assert parse_date("06.11.2026") == "2026-11-06"
    assert parse_date("09 November 2026") == "2026-11-09"
    assert parse_date("4 Dec, 2026") == "2026-12-04"
    print("parse_date OK")

def test_classify():
    assert classify_rule("Safety at height seminar") == "H&S"
    assert classify_rule("NEC contract workshop") == "GPM"
    assert classify_rule("Structural analysis lecture") == "Technical"
    print("classify_rule OK")

if __name__ == "__main__":
    test_parse_date()
    test_classify()
    print("All tests passed")
