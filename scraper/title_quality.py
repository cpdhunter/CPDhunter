"""Conservative event-title quality checks: detect/reject, never rewrite."""
from __future__ import annotations

import re
from typing import Optional, Tuple

# Exact UI / filter / badge labels that must never be stored as titles.
HKGBC_BADGES = frozenset({
    "supporting event",
    "hkgbc event",
    "cpd event",
})

CIC_EVENT_TYPE_LABELS = frozenset({
    "job fair",
    "conference／seminar",
    "conference/seminar",
    "exhibition",
    "festival",
    "others",
    "ceremony",
    "tour",
    "workshop",
    "award／competition",
    "award/competition",
})

FILTER_LABELS = HKGBC_BADGES | CIC_EVENT_TYPE_LABELS

TIME_ONLY_RE = re.compile(
    r"^\d{1,2}:\d{2}\s*[-–—]\s*\d{1,2}:\d{2}$"
)

# Date / date-range only (optional weekday parenthetical).
DATE_ONLY_RE = re.compile(
    r"""^
    (?:
        \d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}                          # 11 December 2026
      | \d{1,2}\s*&\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}            # 28 & 29 December 2026
      | \d{1,2}\s*&\s*\d{1,2}-\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}    # 4 & 7-11 December 2026
      | \d{1,2}-\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}                  # 9-11 Dec 2026 / 14-18 December 2026
      | \d{1,2}/\d{1,2}/\d{4}
      | \d{4}-\d{1,2}-\d{1,2}
      | \d{1,2}\.\d{1,2}\.\d{4}
    )
    (?:\s*\([^)]*\))?
    $""",
    re.I | re.X,
)

HKGBC_BADGE_PREFIX_RE = re.compile(
    r"^(?:Supporting Event|HKGBC Event|CPD Event)(?:\s*[,|]\s*|\s+)+",
    re.I,
)

CHROME_LEAD_RE = re.compile(
    r"^(?:Begins\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}\s*)+",
    re.I,
)
CHROME_TRAIL_RE = re.compile(
    r"(?:\s*Find out more\s*)+$",
    re.I,
)
SKIP_TO_RE = re.compile(r"^Skip to\b.*", re.I)

TITLE_SOFT_LIMIT = 500


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def strip_hkgbc_badges(title: str) -> str:
    """Iteratively strip HKGBC category badge prefixes."""
    t = normalize_ws(title)
    if t.lower() in HKGBC_BADGES:
        return ""
    # Also drop leading date|badge chrome: "12 Jan 2027 | Supporting Event ..."
    t = re.sub(
        r"^\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s*\|\s*",
        "",
        t,
    )
    prev = None
    while prev != t:
        prev = t
        if t.lower() in HKGBC_BADGES:
            return ""
        t = HKGBC_BADGE_PREFIX_RE.sub("", t).strip()
        t = re.sub(r"^[,|\s]+", "", t).strip()
    if t.lower() in HKGBC_BADGES:
        return ""
    return t


def strip_page_chrome(title: str) -> str:
    """Remove structurally obvious listing chrome; do not editorially shorten."""
    t = normalize_ws(title)
    if SKIP_TO_RE.match(t):
        return ""
    t = CHROME_LEAD_RE.sub("", t).strip()
    t = CHROME_TRAIL_RE.sub("", t).strip()
    # Collapse duplicated "Begins … Title Begins …" mid-string leftovers
    t = re.sub(
        r"\s*Begins\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}\s*",
        " ",
        t,
        flags=re.I,
    )
    t = CHROME_TRAIL_RE.sub("", normalize_ws(t)).strip()
    return t


def clamp_title(title: str, limit: int = TITLE_SOFT_LIMIT) -> str:
    """Hard safety cap; prefer last whitespace before limit (no mid-word cut at 200)."""
    t = normalize_ws(title)
    if len(t) <= limit:
        return t
    cut = t[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip() or t[:limit]


def is_time_only_title(title: str) -> bool:
    return bool(TIME_ONLY_RE.match(normalize_ws(title)))


def is_date_only_title(title: str) -> bool:
    t = normalize_ws(title)
    if not t:
        return False
    return bool(DATE_ONLY_RE.match(t))


def is_filter_or_badge_title(title: str) -> bool:
    return normalize_ws(title).lower() in FILTER_LABELS


def title_quality_reason(title: str) -> Optional[str]:
    """
    Return a diagnostic reason if title is impossible, else None.
    Detection/rejection only — never rewrites.
    """
    t = normalize_ws(title)
    if not t:
        return "empty"
    if is_time_only_title(t):
        return "time_only"
    if is_date_only_title(t):
        return "date_only"
    if is_filter_or_badge_title(t):
        return "filter_or_badge"
    # Unstripped HKGBC category prefixes (contaminated stored titles)
    if re.match(r"^(?:Supporting Event|HKGBC Event|CPD Event)\b", t, re.I):
        return "hkgbc_badge_prefix"
    stripped = strip_hkgbc_badges(t)
    if not stripped or is_filter_or_badge_title(stripped):
        if HKGBC_BADGE_PREFIX_RE.match(t) or t.lower() in HKGBC_BADGES:
            return "hkgbc_badge"
    # Listing chrome concatenation (e.g. CIC UK card dump)
    if re.search(r"\bBegins\s+\d", t, re.I) and re.search(r"Find out more", t, re.I):
        return "page_chrome"
    if re.match(r"^Begins\s+\d", t, re.I):
        return "page_chrome"
    return None


def is_good_title(title: str) -> bool:
    return title_quality_reason(title) is None


def validate_title(title: str) -> Tuple[bool, Optional[str]]:
    reason = title_quality_reason(title)
    return reason is None, reason
