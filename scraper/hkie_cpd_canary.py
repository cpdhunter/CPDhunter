"""HKIE CPD-only Scrapling production canary.

Scrapling may be selected only when quality gates prove it is at least as
trustworthy as the legacy parser. When uncertain, use legacy.
A false event is worse than a missed event.

Rollback (no code removal, no git history rollback):
    HKIE_SCRAPLING_CANARY = False
    or environment HKIE_SCRAPLING_CANARY=0/false/off

Stage 1 (default): compute gates only; production always uses legacy.
Stage 2: may select the complete Scrapling set when all gates pass AND
there is material benefit. Still falls back to legacy when uncertain.

CIC and HKGBC are not on this path. The legacy extractor remains callable.
Scrapling is an optional dependency; import/install/parse failures fall back
to legacy and must not fail Daily CPD.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# python scraper/fetch.py puts only scraper/ on sys.path, so "import scraper"
# fails in Actions unless the repo root is added. Tests may already set
# PYTHONPATH; inserting is harmless if the path is already present.
_SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRAPER_DIR)
for _p in (_REPO_ROOT, _SCRAPER_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- Rollback / stage switches ------------------------------------------------
# Turning HKIE_SCRAPLING_CANARY off restores legacy-only HKIE behaviour.
HKIE_SCRAPLING_CANARY = True
# 1 = shadow + gate calculation only (production stays legacy)
# 2 = allow Scrapling to be selected when gates pass and there is benefit
HKIE_SCRAPLING_CANARY_STAGE = 1

SOURCE_LABEL = "HKIE CPD Calendar"
SCRAPLING_PIN = "scrapling==0.5.1"

CANARY_PASS_SCRAPLING = "CANARY_PASS_SCRAPLING"
CANARY_PASS_LEGACY = "CANARY_PASS_LEGACY"
CANARY_FAIL = "CANARY_FAIL"
CANARY_REVIEW = "CANARY_REVIEW"
CANARY_DISABLED = "CANARY_DISABLED"

STATUS_SELECT_LEGACY = {CANARY_PASS_LEGACY, CANARY_FAIL, CANARY_REVIEW, CANARY_DISABLED}

VALID_MODES = frozenset({"ONLINE", "FACE_TO_FACE", "HYBRID"})

HKIE_LISTING_PATH = "/professional-development/continuing-professional-development/cpd-calendar"
_CHROME_CLASS_RE = re.compile(
    r"sidebar|side-bar|side_bar|site-nav|navbar|nav-menu|main-nav|"
    r"breadcrumb|site-footer|mega-menu|offcanvas|cookie-banner|widget-nav",
    re.I,
)
_CHROME_TAGS = frozenset({"nav", "footer", "header", "aside"})
_GENERIC_HEADING_RE = re.compile(
    r"^(cpd calendar|cpd courses|upcoming (?:hkie )?events|upcoming courses|"
    r"courses|events|news|professional development|"
    r"continuing professional development|category|categories|"
    r"filter|search|menu|home|contact|login|membership|about(?: us)?|"
    r"privacy policy|terms of use|cookie policy)$",
    re.I,
)
_NAV_PATH_RE = re.compile(
    r"/(about|membership|login|contact|privacy|terms|cookie|search|account|register)(/|$)",
    re.I,
)
_COURSE_PATH_RE = re.compile(r"/(cpd-courses|events?|courses?)/", re.I)

# Production raw fields that may pass through to clean(). Shadow-only
# diagnostics are never copied into the selected set.
_RAW_PASSTHROUGH = (
    "title",
    "date",
    "url",
    "organizer",
    "start_time",
    "end_time",
    "cpd_hours",
    "is_online",
    "is_free",
    "type",
    "disciplines",
    "registration_destination",
    "venue",
    "location",
    "modeText",
    "attendanceMode",
    "description",
    "venueSource",
    "time",
    "time_raw",
    "time_s",
    "duration",
    "hours_text",
)

_LAST_DIAG: Optional[Dict[str, Any]] = None
_INSTALL_ATTEMPTED = False

_ARTIFACT_NAME = "hkie-canary.json"
_STATE_NAME = "hkie-canary-state.json"

HEALTH_DIAG_KEYS = (
    "stage",
    "enabled",
    "scrapling_version",
    "legacy_count",
    "scrapling_count",
    "matched_count",
    "legacy_only",
    "scrapling_only",
    "title_mismatches",
    "date_mismatches",
    "url_mismatches",
    "adaptive_match_used",
    "adaptive_recovery_count",
    "adaptive_false_positive_count",
    "selected_result",
    "canary_status",
    "would_select",
    "material_benefit",
    "reason",
    "legacy_ms",
    "scrapling_ms",
    "adaptive_state_bytes",
    "gates",
)


def _truthy_env(name: str) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip().lower() not in ("0", "false", "off", "no")


def canary_enabled() -> bool:
    env = _truthy_env("HKIE_SCRAPLING_CANARY")
    if env is not None:
        return env
    return bool(HKIE_SCRAPLING_CANARY)


def canary_stage() -> int:
    raw = os.getenv("HKIE_SCRAPLING_CANARY_STAGE")
    if raw and raw.strip().isdigit():
        return max(1, min(int(raw.strip()), 2))
    stage = int(HKIE_SCRAPLING_CANARY_STAGE)
    return max(1, min(stage, 2))


def last_diagnostic() -> Optional[Dict[str, Any]]:
    return copy.deepcopy(_LAST_DIAG) if _LAST_DIAG else None


def reset_last_diagnostic() -> None:
    global _LAST_DIAG
    _LAST_DIAG = None


def _log(*parts: Any) -> None:
    print("[hkie-canary]", *parts, file=sys.stderr, flush=True)


def _artifacts_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "shadow", "artifacts")
    os.makedirs(path, exist_ok=True)
    return path


def canary_artifact_path() -> str:
    return os.path.join(_artifacts_dir(), _ARTIFACT_NAME)


def canary_state_path() -> str:
    return os.path.join(_artifacts_dir(), _STATE_NAME)


def _scrapling_version() -> Optional[str]:
    try:
        import scrapling  # type: ignore

        return getattr(scrapling, "__version__", "unknown")
    except Exception:
        return None


def ensure_scrapling() -> Tuple[bool, Optional[str]]:
    """Best-effort optional install of the pinned Scrapling wheel. Never raises."""
    global _INSTALL_ATTEMPTED
    try:
        import scrapling  # noqa: F401

        return True, None
    except Exception as ex:
        first = f"{type(ex).__name__}: {ex}"
    if _INSTALL_ATTEMPTED:
        return False, first
    _INSTALL_ATTEMPTED = True
    try:
        import subprocess

        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", SCRAPLING_PIN],
            check=False,
            timeout=180,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import scrapling  # noqa: F401

        return True, None
    except Exception as ex:
        return False, f"{first}; install: {type(ex).__name__}: {ex}"


def _is_chrome_title(title: str) -> bool:
    t = " ".join((title or "").split()).strip()
    if not t:
        return True
    return bool(_GENERIC_HEADING_RE.match(t))


def _attr_blob(el: Any) -> str:
    bits: List[str] = []
    for key in ("class", "id", "role", "tag"):
        val = None
        if hasattr(el, "attrib"):
            try:
                val = el.attrib.get(key)
            except Exception:
                val = None
        if val is None:
            try:
                val = el.attrs.get(key) if hasattr(el, "attrs") else getattr(el, key, None)
            except Exception:
                val = None
        if val is None and key == "tag":
            val = getattr(el, "tag", None)
        if isinstance(val, (list, tuple)):
            bits.append(" ".join(str(x) for x in val))
        elif val:
            bits.append(str(val))
    return " ".join(bits)


def node_looks_like_chrome(card: Any) -> bool:
    """Reject sidebar / nav / footer / generic category nodes (GATE D)."""
    cur = card
    for _ in range(8):
        if cur is None:
            break
        tag = str(getattr(cur, "tag", "") or "").lower()
        blob = _attr_blob(cur)
        if tag in _CHROME_TAGS or _CHROME_CLASS_RE.search(blob):
            return True
        parent = getattr(cur, "parent", None)
        cur = parent if parent is not None and parent is not cur else None
    return False


def is_official_hkie_course_url(url: Optional[str], listing_base: str) -> bool:
    """GATE C: a present detail URL must be an official HKIE course/event URL.

    The listing page used as a fallback (no card link) is treated as 'no detail'
    and is allowed. Navigation/account URLs are not.
    """
    if not url:
        return True
    if not str(url).startswith("http"):
        return False
    parsed = urlparse(url)
    base = urlparse(listing_base)
    host = (parsed.netloc or "").lower()
    path = parsed.path or "/"
    if path.rstrip("/") == (base.path or "/").rstrip("/"):
        return True
    if "hkie.org.hk" not in host and not host.endswith("hkie.org"):
        return False
    if _NAV_PATH_RE.search(path):
        return False
    if path.rstrip("/") == HKIE_LISTING_PATH.rstrip("/"):
        return True
    return bool(_COURSE_PATH_RE.search(path))


def _title_ok(title: str) -> Tuple[bool, Optional[str]]:
    from title_quality import is_date_only_title, is_time_only_title, title_quality_reason

    if not (title or "").strip():
        return False, "empty"
    if is_date_only_title(title):
        return False, "date_only"
    if is_time_only_title(title):
        return False, "time_only"
    if _is_chrome_title(title):
        return False, "navigation_chrome"
    reason = title_quality_reason(title)
    if reason:
        return False, reason
    return True, None


def to_legacy_raw(ev: Dict[str, Any], organizer: str = "HKIE") -> Dict[str, Any]:
    """Normalize a Scrapling (or mixed) event to the production raw schema.

    Does not copy shadow diagnostics. Does not invent attendance modes.
    mode=UNKNOWN is omitted so clean()/attach_mode stay unchanged.
    """
    out: Dict[str, Any] = {}
    for key in _RAW_PASSTHROUGH:
        if key in ev and ev[key] is not None:
            out[key] = ev[key]
    out["title"] = ev.get("title") or ev.get("name") or ""
    out["date"] = ev.get("date")
    out["url"] = ev.get("url")
    out["organizer"] = ev.get("organizer") or organizer
    if ev.get("start_time"):
        out["start_time"] = ev["start_time"]
    if ev.get("end_time"):
        out["end_time"] = ev["end_time"]
    # Only organiser-stated hours. Estimated hours from a time range are
    # left to clean()/hours_from_range so hrs_est stays accurate.
    if ev.get("cpd_hours") is not None:
        out["cpd_hours"] = ev["cpd_hours"]
    mode = ev.get("mode")
    if isinstance(mode, str) and mode.strip().upper() in VALID_MODES:
        out["mode"] = mode.strip().upper()
    dest = ev.get("registration_destination") or ev.get("registration_url")
    if isinstance(dest, str) and dest.startswith("http"):
        # registration_url on shadow events often duplicates the detail URL;
        # only keep it when it looks like a distinct registration destination.
        detail = ev.get("url") or ""
        if dest != detail or ev.get("registration_destination"):
            if dest != detail:
                out["registration_destination"] = dest
    return out


def legacy_hkie_cpd_extract(soup, base: str) -> List[Dict[str, Any]]:
    """Always-callable legacy extractor. The Scrapling path must not mutate this."""
    from fetch import extract_hkie_cpd

    return list(extract_hkie_cpd(soup, base) or [])


def _min_structure_ok(ev: Optional[Dict[str, Any]], listing_base: str) -> bool:
    if not ev:
        return False
    ok, _ = _title_ok(ev.get("title") or "")
    if not ok:
        return False
    from fetch import parse_date

    if not parse_date(ev.get("date")):
        return False
    return is_official_hkie_course_url(ev.get("url"), listing_base)


def scrapling_hkie_cpd_extract(
    html: str,
    base: str,
    storage_file: Optional[str] = None,
    adaptive: bool = True,
) -> Dict[str, Any]:
    """Course-card-scoped Scrapling extract + GATE D adaptive safety.

    Returns a dict with `events` already converted to legacy raw schema.
    On any error, events is empty and `error` is set — callers fall back.
    """
    from scraper.shadow.adaptive import AUTO_MATCH_FALSE_POSITIVE, AUTO_MATCH_RECOVERED
    from scraper.shadow.paths import IDENT_HKIE_CARD
    from scraper.shadow.scrapling_hkie_cpd import (
        CARD_CSS,
        FALLBACK_CSS,
        _extract_from_card,
    )
    from scraper.shadow.selector_util import element_text, make_selector

    storage_file = storage_file or canary_state_path()
    out: Dict[str, Any] = {
        "events": [],
        "candidate_count": 0,
        "valid_title_count": 0,
        "selector_strategy": CARD_CSS,
        "adaptive_match_used": False,
        "adaptive_recovery_count": 0,
        "adaptive_false_positive_count": 0,
        "adaptive_status": None,
        "error": None,
        "state_bytes": 0,
    }
    try:
        parent = os.path.dirname(os.path.abspath(storage_file))
        if parent:
            os.makedirs(parent, exist_ok=True)
        page = make_selector(html, base, storage_file, adaptive=True)
        cards = page.css(CARD_CSS) or []
        selector_used = CARD_CSS
        adaptive_used = False
        if not cards:
            fallback = []
            for wrap in page.css(FALLBACK_CSS) or []:
                if re.search(r"\bCPD\d{3,}/\d{4}\b", element_text(wrap)):
                    fallback.append(wrap)
            cards = fallback
            if cards:
                selector_used = FALLBACK_CSS
        recovered_status = None
        if not cards and adaptive:
            recovered = page.css(CARD_CSS, adaptive=True, identifier=IDENT_HKIE_CARD) or []
            kept = []
            fp = 0
            for card in recovered:
                if node_looks_like_chrome(card):
                    fp += 1
                    continue
                ev = _extract_from_card(card, base, f"{CARD_CSS}#adaptive:{IDENT_HKIE_CARD}", True)
                if not _min_structure_ok(ev, base):
                    fp += 1
                    continue
                kept.append(card)
            out["adaptive_false_positive_count"] = fp
            if kept and fp == 0:
                recovered_status = AUTO_MATCH_RECOVERED
                adaptive_used = True
                cards = kept
                selector_used = f"{CARD_CSS}#adaptive:{IDENT_HKIE_CARD}"
                out["adaptive_recovery_count"] = len(kept)
            elif recovered:
                # An element came back but failed min structure / chrome checks.
                recovered_status = AUTO_MATCH_FALSE_POSITIVE
                cards = []
            else:
                recovered_status = "AUTO_MATCH_FAILED"
                cards = []
            out["adaptive_status"] = recovered_status
            out["adaptive_match_used"] = adaptive_used

        events: List[Dict[str, Any]] = []
        for card in cards or []:
            if adaptive_used and node_looks_like_chrome(card):
                out["adaptive_false_positive_count"] += 1
                continue
            ev = _extract_from_card(card, base, selector_used, adaptive_used)
            if not ev:
                if adaptive_used:
                    out["adaptive_false_positive_count"] += 1
                continue
            if not _min_structure_ok(ev, base):
                if adaptive_used:
                    out["adaptive_false_positive_count"] += 1
                    out["adaptive_status"] = AUTO_MATCH_FALSE_POSITIVE
                continue
            events.append(to_legacy_raw(ev))

        seen = set()
        uniq: List[Dict[str, Any]] = []
        for e in events:
            k = (e.get("date"), (e.get("title") or "")[:80])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(e)
        out["events"] = uniq
        out["candidate_count"] = len(cards or [])
        out["valid_title_count"] = len(uniq)
        out["selector_strategy"] = selector_used
        if os.path.isfile(storage_file):
            out["state_bytes"] = os.path.getsize(storage_file)
        return out
    except Exception as ex:
        out["error"] = f"{type(ex).__name__}: {ex}"
        out["traceback"] = traceback.format_exc(limit=4)
        return out


def _pair_stats(legacy: List[Dict[str, Any]], scrapling: List[Dict[str, Any]]) -> Dict[str, Any]:
    from scraper.shadow.compare_shadow import pair_events

    return pair_events(legacy, scrapling)


def _material_benefit(legacy: List[Dict[str, Any]], scrapling: List[Dict[str, Any]], stats: Dict[str, Any], meta: Dict[str, Any]) -> Tuple[bool, str]:
    """Benefit is a more complete trustworthy set, not a mere parser swap."""
    if meta.get("adaptive_match_used") and meta.get("adaptive_recovery_count", 0) > 0:
        if stats.get("date_mismatches", 0) == 0 and stats.get("title_mismatches", 0) == 0:
            return True, "adaptive_recovery_of_valid_cards"
    # Extra complete hours/times on matched events, no conflicts.
    richer = 0
    # Re-pair to inspect fields: use title+date equality.
    def key(e):
        return (" ".join((e.get("title") or e.get("name") or "").split()).lower(), e.get("date") or "")

    lmap = {key(e): e for e in legacy}
    for s in scrapling:
        l = lmap.get(key(s))
        if not l:
            continue
        if s.get("cpd_hours") is not None and l.get("cpd_hours") is None:
            richer += 1
        if s.get("start_time") and not l.get("start_time"):
            richer += 1
    scrapling_only = int(stats.get("scrapling_only") or stats.get("shadow_only") or 0)
    if richer and stats.get("date_mismatches", 0) == 0 and stats.get("title_mismatches", 0) == 0:
        if scrapling_only == 0:
            return True, "richer_hours_or_times_on_matched_events"
    if (
        scrapling_only > 0
        and scrapling_only <= 2
        and stats.get("date_mismatches", 0) == 0
        and stats.get("title_mismatches", 0) == 0
        and len(scrapling) >= len(legacy)
    ):
        extras_ok = all(_title_ok(t)[0] and e.get("date") for e, t in ((e, e.get("title") or "") for e in scrapling))
        if extras_ok:
            return True, "small_explained_extra_valid_events"
    return False, "no_material_benefit"


def evaluate_canary(
    legacy: List[Dict[str, Any]],
    scrapling: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
    listing_base: str = "https://hkie.org.hk/professional-development/continuing-professional-development/cpd-calendar/",
) -> Dict[str, Any]:
    """Pure gate evaluation. Never writes catalog files. Does not mix A+B."""
    meta = dict(meta or {})
    L, S = len(legacy), len(scrapling)
    gates = {g: "PASS" for g in list("ABCDEFG")}
    reasons: List[str] = []
    fail = False
    review = False

    if meta.get("error"):
        gates["A"] = "FAIL"
        reasons.append(f"scrapling_error:{meta['error']}")
        fail = True

    # GATE A / G title quality on every scrapling event
    for ev in scrapling:
        ok, reason = _title_ok(ev.get("title") or "")
        if not ok:
            gates["A"] = "FAIL"
            gates["G"] = "FAIL"
            reasons.append(f"title:{reason}")
            fail = True
            break

    # GATE C URLs
    for ev in scrapling:
        if not is_official_hkie_course_url(ev.get("url"), listing_base):
            gates["C"] = "FAIL"
            reasons.append("unofficial_or_nav_url")
            fail = True
            break

    # GATE D: adaptive false positives block selection
    if meta.get("adaptive_false_positive_count", 0) > 0:
        gates["D"] = "FAIL"
        reasons.append("adaptive_false_positive")
        fail = True
    elif meta.get("adaptive_status") == "AUTO_MATCH_FALSE_POSITIVE":
        gates["D"] = "FAIL"
        reasons.append("adaptive_false_positive")
        fail = True

    stats = _pair_stats(legacy, scrapling) if not meta.get("skip_pair") else {
        "matched_events": 0,
        "production_only": L,
        "shadow_only": S,
        "title_mismatches": 0,
        "date_mismatches": 0,
        "url_matches": 0,
    }
    title_mm = int(stats.get("title_mismatches") or 0)
    date_mm = int(stats.get("date_mismatches") or 0)
    url_mm = 0
    # url mismatches among matched pairs: pair_events gives url_matches
    matched = int(stats.get("matched_events") or 0)
    url_mm = max(0, matched - int(stats.get("url_matches") or 0))

    # GATE F: conflicting date on a matched pair is a FAIL
    if date_mm:
        gates["F"] = "FAIL"
        reasons.append("date_mismatch_on_matched_pair")
        fail = True
    if title_mm:
        # Title disagreement on a matched (usually URL-matched) record: review, not auto-prefer
        gates["F"] = "REVIEW" if gates["F"] == "PASS" else gates["F"]
        reasons.append("title_mismatch_on_matched_pair")
        review = True

    # GATE B is guaranteed by same-container extraction; a date mismatch
    # already failed F/G. Adjacent-card swaps show up as date mismatches.
    if date_mm:
        gates["B"] = "FAIL"
        gates["G"] = "FAIL"

    # GATE E count sanity
    explosion_cap = max(L * 1.5, L + 5)
    if L > 0 and S == 0:
        gates["E"] = "REVIEW"
        reasons.append("scrapling_zero_legacy_nonzero")
        review = True
    elif S > explosion_cap:
        gates["E"] = "REVIEW"
        reasons.append("candidate_explosion")
        review = True
    else:
        delta = abs(S - L)
        unexplained = False
        if delta > 2:
            unexplained = True
        if date_mm or title_mm:
            unexplained = True if delta else unexplained
        if unexplained:
            gates["E"] = "REVIEW"
            reasons.append("unexplained_count_delta")
            review = True

    benefit, benefit_reason = _material_benefit(legacy, scrapling, stats, meta)

    if fail:
        status = CANARY_FAIL
    elif review:
        status = CANARY_REVIEW
    elif benefit:
        status = CANARY_PASS_SCRAPLING
    else:
        status = CANARY_PASS_LEGACY
        reasons.append(benefit_reason or "no_material_benefit")

    would_select = "scrapling" if status == CANARY_PASS_SCRAPLING else "legacy"
    return {
        "canary_status": status,
        "would_select": would_select,
        "material_benefit": bool(benefit and status == CANARY_PASS_SCRAPLING),
        "reason": ";".join(reasons) if reasons else status,
        "gates": gates,
        "legacy_count": L,
        "scrapling_count": S,
        "matched_count": matched,
        "legacy_only": int(stats.get("production_only") or 0),
        "scrapling_only": int(stats.get("shadow_only") or 0),
        "title_mismatches": title_mm,
        "date_mismatches": date_mm,
        "url_mismatches": url_mm,
        "legacy_only_titles": (stats.get("production_only_titles") or [])[:5],
        "scrapling_only_titles": (stats.get("shadow_only_titles") or [])[:5],
        "benefit_reason": benefit_reason,
    }


def choose_result_set(
    legacy: List[Dict[str, Any]],
    scrapling: List[Dict[str, Any]],
    decision: Dict[str, Any],
    stage: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], str, str]:
    """Pick one complete set. Never merge A+B. Stage 1 always returns legacy."""
    stage = canary_stage() if stage is None else stage
    status = decision["canary_status"]
    # Deep copy so later clean/dedup cannot mutate the other branch.
    legacy_copy = copy.deepcopy(legacy)
    scrapling_copy = copy.deepcopy(scrapling)
    if stage < 2 or status != CANARY_PASS_SCRAPLING:
        return legacy_copy, "legacy", status
    return scrapling_copy, "scrapling", status


def _compact_diag(diag: Dict[str, Any]) -> Dict[str, Any]:
    return {k: diag[k] for k in HEALTH_DIAG_KEYS if k in diag}


def write_canary_artifact(diag: Dict[str, Any]) -> Optional[str]:
    try:
        path = canary_artifact_path()
        payload = {k: v for k, v in diag.items() if k != "traceback"}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return path
    except Exception as ex:
        _log("artifact write skipped:", type(ex).__name__, ex)
        return None


def attach_health_diagnostic(health: Dict[str, Any]) -> None:
    """Attach compact canary metadata to the HKIE health entry. Does not change rules."""
    if not _LAST_DIAG:
        return
    entry = health.get(SOURCE_LABEL)
    if not isinstance(entry, dict):
        return
    entry["canary"] = _compact_diag(_LAST_DIAG)


def extract_hkie_cpd_with_canary(
    soup,
    base: str,
    html: Optional[str] = None,
    storage_file: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Production hook: dual-extract, gate, select one complete set.

    Returns (raw_events, method). method stays 'hkie-cpd' so source-health
    rules are unchanged. Diagnostics live on last_diagnostic() / artifact.
    """
    global _LAST_DIAG
    from bs4 import BeautifulSoup

    stage = canary_stage()
    enabled = canary_enabled()
    html = html if isinstance(html, str) and html.strip() else str(soup)
    if soup is None:
        soup = BeautifulSoup(html, "html.parser")

    t0 = time.perf_counter()
    legacy = legacy_hkie_cpd_extract(soup, base)
    # Freeze a copy immediately so the Scrapling path cannot mutate it.
    legacy_frozen = copy.deepcopy(legacy)
    legacy_ms = round((time.perf_counter() - t0) * 1000, 2)

    diag: Dict[str, Any] = {
        "stage": stage,
        "enabled": enabled,
        "scrapling_version": _scrapling_version(),
        "legacy_count": len(legacy_frozen),
        "scrapling_count": None,
        "matched_count": None,
        "legacy_only": None,
        "scrapling_only": None,
        "title_mismatches": None,
        "date_mismatches": None,
        "url_mismatches": None,
        "adaptive_match_used": False,
        "adaptive_recovery_count": 0,
        "adaptive_false_positive_count": 0,
        "selected_result": "legacy",
        "canary_status": CANARY_DISABLED,
        "would_select": "legacy",
        "material_benefit": False,
        "reason": "canary_disabled",
        "legacy_ms": legacy_ms,
        "scrapling_ms": None,
        "adaptive_state_bytes": 0,
        "gates": {},
    }

    if not enabled:
        _LAST_DIAG = diag
        write_canary_artifact(diag)
        _log("disabled; using legacy", "L=", len(legacy_frozen))
        return copy.deepcopy(legacy_frozen), "hkie-cpd"

    ok, err = ensure_scrapling()
    if not ok:
        diag["canary_status"] = CANARY_FAIL
        diag["reason"] = f"scrapling_unavailable:{err}"
        _LAST_DIAG = diag
        write_canary_artifact(diag)
        _log("scrapling unavailable; using legacy:", err)
        return copy.deepcopy(legacy_frozen), "hkie-cpd"

    diag["scrapling_version"] = _scrapling_version()
    t1 = time.perf_counter()
    try:
        extracted = scrapling_hkie_cpd_extract(
            html, base, storage_file=storage_file or canary_state_path(), adaptive=True
        )
    except Exception as ex:
        extracted = {
            "events": [],
            "error": f"{type(ex).__name__}: {ex}",
            "adaptive_match_used": False,
            "adaptive_recovery_count": 0,
            "adaptive_false_positive_count": 0,
            "state_bytes": 0,
        }
    scrapling_ms = round((time.perf_counter() - t1) * 1000, 2)
    diag["scrapling_ms"] = scrapling_ms
    diag["adaptive_state_bytes"] = int(extracted.get("state_bytes") or 0)
    diag["adaptive_match_used"] = bool(extracted.get("adaptive_match_used"))
    diag["adaptive_recovery_count"] = int(extracted.get("adaptive_recovery_count") or 0)
    diag["adaptive_false_positive_count"] = int(extracted.get("adaptive_false_positive_count") or 0)
    diag["adaptive_status"] = extracted.get("adaptive_status")
    diag["selector_strategy"] = extracted.get("selector_strategy")

    scrapling_events = list(extracted.get("events") or [])
    # Guard: never let scrapling mutate the frozen legacy list (identity check).
    assert scrapling_events is not legacy and scrapling_events is not legacy_frozen

    meta = {
        "error": extracted.get("error"),
        "adaptive_match_used": diag["adaptive_match_used"],
        "adaptive_recovery_count": diag["adaptive_recovery_count"],
        "adaptive_false_positive_count": diag["adaptive_false_positive_count"],
        "adaptive_status": extracted.get("adaptive_status"),
    }
    try:
        decision = evaluate_canary(legacy_frozen, scrapling_events, meta, listing_base=base)
    except Exception as ex:
        decision = {
            "canary_status": CANARY_FAIL,
            "would_select": "legacy",
            "material_benefit": False,
            "reason": f"comparison_failure:{type(ex).__name__}: {ex}",
            "gates": {},
            "legacy_count": len(legacy_frozen),
            "scrapling_count": len(scrapling_events),
            "matched_count": 0,
            "legacy_only": len(legacy_frozen),
            "scrapling_only": len(scrapling_events),
            "title_mismatches": 0,
            "date_mismatches": 0,
            "url_mismatches": 0,
        }

    raw, selected, status = choose_result_set(legacy_frozen, scrapling_events, decision, stage=stage)
    diag.update({
        "legacy_count": decision.get("legacy_count", len(legacy_frozen)),
        "scrapling_count": decision.get("scrapling_count", len(scrapling_events)),
        "matched_count": decision.get("matched_count"),
        "legacy_only": decision.get("legacy_only"),
        "scrapling_only": decision.get("scrapling_only"),
        "title_mismatches": decision.get("title_mismatches"),
        "date_mismatches": decision.get("date_mismatches"),
        "url_mismatches": decision.get("url_mismatches"),
        "selected_result": selected,
        "canary_status": status,
        "would_select": decision.get("would_select"),
        "material_benefit": decision.get("material_benefit"),
        "reason": decision.get("reason"),
        "gates": decision.get("gates") or {},
        "legacy_only_titles": decision.get("legacy_only_titles") or [],
        "scrapling_only_titles": decision.get("scrapling_only_titles") or [],
        "stage_forced_legacy": stage < 2 and selected == "legacy",
    })
    _LAST_DIAG = diag
    write_canary_artifact(diag)
    _log(
        f"stage={stage} status={status} selected={selected} "
        f"L={diag['legacy_count']} S={diag['scrapling_count']} "
        f"matched={diag['matched_count']} "
        f"legacy_ms={legacy_ms} scrapling_ms={scrapling_ms} "
        f"reason={diag['reason']}"
    )
    return raw, "hkie-cpd"
