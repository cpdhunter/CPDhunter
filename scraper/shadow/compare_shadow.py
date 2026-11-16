"""Diagnostic-only comparison of production parser output vs Scrapling shadow events.

Matching is NOT fed into production deduplication.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

_WS = re.compile(r"\s+")


def _norm_title(s: str) -> str:
    return _WS.sub(" ", (s or "").strip()).lower()


def _prod_title(ev: Dict[str, Any]) -> str:
    return ev.get("title") or ev.get("name") or ""


def _date(ev: Dict[str, Any]) -> str:
    return ev.get("date") or ""


def _url(ev: Dict[str, Any]) -> str:
    return ev.get("url") or ev.get("registration_url") or ""


def _similar(a: str, b: str, threshold: float = 0.85) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio() >= threshold


def pair_events(production: List[Dict[str, Any]], shadow: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Match records: 1) exact title+date, 2) same detail URL, 3) same date + high title similarity."""
    prod = list(production)
    shad = list(shadow)
    used_p, used_s = set(), set()
    pairs: List[Tuple[int, int, str]] = []

    def take(i: int, j: int, how: str):
        if i in used_p or j in used_s:
            return
        used_p.add(i)
        used_s.add(j)
        pairs.append((i, j, how))

    for i, p in enumerate(prod):
        for j, s in enumerate(shad):
            if j in used_s:
                continue
            if _norm_title(_prod_title(p)) == _norm_title(s.get("title") or "") and _date(p) and _date(p) == _date(s):
                take(i, j, "title_date")

    for i, p in enumerate(prod):
        if i in used_p:
            continue
        pu = _url(p)
        if not pu:
            continue
        for j, s in enumerate(shad):
            if j in used_s:
                continue
            if pu == _url(s):
                take(i, j, "url")

    for i, p in enumerate(prod):
        if i in used_p:
            continue
        if not _date(p):
            continue
        for j, s in enumerate(shad):
            if j in used_s:
                continue
            if _date(p) == _date(s) and _similar(_prod_title(p), s.get("title") or ""):
                take(i, j, "date_similar_title")

    title_matches = date_matches = url_matches = title_mismatches = date_mismatches = 0
    for i, j, _how in pairs:
        p, s = prod[i], shad[j]
        if _norm_title(_prod_title(p)) == _norm_title(s.get("title") or ""):
            title_matches += 1
        else:
            title_mismatches += 1
        if _date(p) and _date(p) == _date(s):
            date_matches += 1
        else:
            date_mismatches += 1
        if _url(p) and _url(p) == _url(s):
            url_matches += 1

    production_only = [prod[i] for i in range(len(prod)) if i not in used_p]
    shadow_only = [shad[j] for j in range(len(shad)) if j not in used_s]
    return {
        "production_count": len(prod),
        "shadow_count": len(shad),
        "matched_events": len(pairs),
        "production_only": len(production_only),
        "shadow_only": len(shadow_only),
        "title_matches": title_matches,
        "title_mismatches": title_mismatches,
        "date_matches": date_matches,
        "date_mismatches": date_mismatches,
        "url_matches": url_matches,
        "false_positive_candidates": len(shadow_only),
        "pair_methods": [how for _, _, how in pairs],
        "production_only_titles": [_prod_title(e) for e in production_only[:10]],
        "shadow_only_titles": [e.get("title") for e in shadow_only[:10]],
    }
