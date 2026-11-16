"""Adaptive-match experiment helpers.

AUTO_MATCH_RECOVERED       — original CSS finds nothing; adaptive returns the SAME event
AUTO_MATCH_FAILED          — original CSS finds nothing; adaptive returns nothing
AUTO_MATCH_FALSE_POSITIVE  — adaptive returns an element that is not the intended event
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, Optional

from .selector_util import element_text, make_selector

AUTO_MATCH_RECOVERED = "AUTO_MATCH_RECOVERED"
AUTO_MATCH_FAILED = "AUTO_MATCH_FAILED"
AUTO_MATCH_FALSE_POSITIVE = "AUTO_MATCH_FALSE_POSITIVE"


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()


def establish_fingerprint(
    html: str,
    url: str,
    storage_file: str,
    css: str,
    identifier: str,
    prefer_text_contains: Optional[str] = None,
) -> Dict[str, Any]:
    """Save the fingerprint of the intended card against current HTML."""
    page = make_selector(html, url, storage_file)
    els = page.css(css)
    if not els:
        raise RuntimeError(f"baseline selector {css!r} matched nothing on {url}")
    chosen = els[0]
    if prefer_text_contains:
        needle = prefer_text_contains.lower()
        for el in els:
            if needle in element_text(el).lower():
                chosen = el
                break
    page.save(chosen, identifier)
    return {
        "identifier": identifier,
        "css": css,
        "saved_text": element_text(chosen),
        "saved_tag": getattr(chosen, "tag", None),
        "storage_file": storage_file,
        "state_bytes": os.path.getsize(storage_file) if os.path.isfile(storage_file) else 0,
    }


def run_adaptive_case(
    *,
    baseline_html: str,
    trial_html: str,
    url: str,
    storage_file: str,
    css: str,
    identifier: str,
    expected_text_contains: str,
    prefer_text_contains: Optional[str] = None,
) -> Dict[str, Any]:
    """Establish fingerprint on baseline HTML, then try css vs adaptive on trial HTML."""
    parent = os.path.dirname(os.path.abspath(storage_file))
    if parent:
        os.makedirs(parent, exist_ok=True)
    saved = establish_fingerprint(
        baseline_html, url, storage_file, css, identifier, prefer_text_contains
    )
    page = make_selector(trial_html, url, storage_file)
    normal = page.css(css)
    adapted = page.css(css, adaptive=True, identifier=identifier)
    if not adapted:
        # Manual relocate fallback (same stored fingerprint).
        stored = page.retrieve(identifier)
        if stored:
            adapted = page.relocate(stored, selector_type=True) or []
    recovered_text = element_text(adapted[0]) if adapted else ""
    recovered_tag = getattr(adapted[0], "tag", None) if adapted else None
    needle = expected_text_contains
    correct = bool(adapted) and _norm(needle) in _norm(recovered_text)
    if not normal and correct:
        status = AUTO_MATCH_RECOVERED
    elif not adapted:
        status = AUTO_MATCH_FAILED
    elif adapted and not correct:
        status = AUTO_MATCH_FALSE_POSITIVE
    else:
        # Original selector still worked — not a drift failure; treat as n/a recover.
        status = AUTO_MATCH_RECOVERED if correct else AUTO_MATCH_FALSE_POSITIVE
    return {
        "status": status,
        "css": css,
        "identifier": identifier,
        "normal_count": len(normal) if normal is not None else 0,
        "adaptive_count": len(adapted) if adapted is not None else 0,
        "original_selector_failed": not bool(normal),
        "recovered_text": recovered_text,
        "recovered_tag": recovered_tag,
        "expected_text_contains": expected_text_contains,
        "correct_event": correct,
        "saved": saved,
    }


def copy_state(src: str, dest: str) -> None:
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        shutil.copy2(src, dest)
