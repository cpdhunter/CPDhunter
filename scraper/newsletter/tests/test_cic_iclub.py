"""Discoverable wrapper. Canonical tests live in scraper/test_newsletter_cic_iclub.py."""
import os
import runpy
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
runpy.run_path(os.path.join(_ROOT, "test_newsletter_cic_iclub.py"), run_name="__main__")
