"""Read-only imports of production helpers. Never run fetch.py as a script."""
from __future__ import annotations

import os
import sys

_SCRAPER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRAPER not in sys.path:
    sys.path.insert(0, _SCRAPER)
