"""Normalize CIC i-Club newsletter candidates and apply pilot quality gates.

Isolated from production import: never writes events.json or source_health.json.
Reuses existing date/time/mode/title-quality/closed-registration/dedup helpers
without changing their rules or global dedup thresholds.
"""
from __future__ import annotations

import os
import re
import sys
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

_SCRAPER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRAPER not in sys.path:
    sys.path.insert(0, _SCRAPER)

import event_mode
from event_mode import infer_mode, strip_registration_channel
from title_quality import is_good_title, title_quality_reason, clamp_title, strip_page_chrome
from fetch import (
    KEEP_DAYS_AHEAD,
    TODAY,
    classify_rule,
    hours_from_range,
    parse_date,
    parse_time_range,
    stated_cpd_hours,
    _norm_title,
    _strong_signal,
    _title_sim,
)
from reg_discover import explicit_closed_registration

DISCOVERY = "NEWSLETTER"
SOURCE_NAME = "CIC i-Club Newsletter"
ORGANISATION = "CIC"

STATUS_ELIGIBLE = "PRODUCTION_ELIGIBLE"
STATUS_REVIEW = "NEWSLETTER_REVIEW"
STATUS_REJECTED = "NEWSLETTER_REJECTED"

MECH_ZOOM_WEBINAR = "ZOOM_WEBINAR"
MECH_ZOOM_MEETING = "ZOOM_MEETING"
MECH_GOOGLE_FORMS = "GOOGLE_FORMS"
MECH_MICROSOFT_FORMS = "MICROSOFT_FORMS"
MECH_EVENTBRITE = "EVENTBRITE"
MECH_CIC_DETAIL = "CIC_EVENT_URL"
MECH_OTHER = "OTHER_PUBLIC_FORM"
MECH_NONE = None

ZOOM_WEBINAR_RE = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)?zoom\.us/webinar/register/[A-Za-z0-9_-]+",
    re.I,
)
ZOOM_MEETING_RE = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)?zoom\.us/meeting/register/[A-Za-z0-9_-]+",
    re.I,
)
ZOOM_JOIN_RE = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)?zoom\.us/j/[0-9]+",
    re.I,
)
GFORM_RE = re.compile(r"https?://(?:forms\.gle/|docs\.google\.com/forms/|google\.com/forms/)", re.I)
MSFORM_RE = re.compile(r"https?://forms\.(?:office|cloud\.microsoft)\.com/", re.I)
EVENTBRITE_RE = re.compile(r"https?://(?:www\.)?eventbrite\.(?:com|hk|co\.uk)/", re.I)
CIC_EVENT_RE = re.compile(
    r"https?://(?:www\.)?(?:cic\.hk|bim\.cic\.hk|citac\.cic\.hk|rstc\.cic\.hk)/",
    re.I,
)

TRACKING_PARAM_RE = re.compile(
    r"^(?:utm_[a-z0-9_]*|fbclid|gclid|gclsrc|mc_[a-z]+|wickedid|igshid|"
    r"pk_[a-z]+|_hsenc|_hsmi|msclkid|mkt_tok|yclid|li_fat_id|twclid)$",
    re.I,
)
PERSONALIZATION_PARAM_RE = re.compile(
    r"^(?:email|e-?mail|recipient|subscriber|contact|uid|user_?id|token|"
    r"auth|hash|sig|signature|unsubscribe|eid|mid|contactid)$",
    re.I,
)

# Construction-site / Civil safety topics (not generic occupational health).
CIVIL_SAFETY_RE = re.compile(
    r"高空工作|大型吊運|重型機械|密閉空間|臨時工程|工作安全|"
    r"地盤|建造業|施工安全|棚架|"
    r"\bsite safety\b|\bwork[-\s]?at[-\s]?height\b|\bworking at height\b|"
    r"\blifting\b|\btemporary works\b|\bconfined space\b|"
    r"\bheavy (?:plant|machinery|equipment)\b|\bconstruction safety\b|"
    r"\bcrane\b|\bscaffold",
    re.I,
)
# Life First / construction safety still maps to H&S even if classify_rule would agree.
HS_TOPIC_RE = re.compile(
    r"高空工作|大型吊運|重型機械|密閉空間|臨時工程|職安|安全|"
    r"\bsite safety\b|\bwork[-\s]?at[-\s]?height\b|\bworking at height\b|"
    r"\blifting\b|\btemporary works\b|\bconfined space\b|"
    r"\bsafety\b|\bhazard\b",
    re.I,
)

SOCIAL_RE = re.compile(
    r"\b(?:dinner|agm|annual general meeting|sport|social|gala|banquet|carnival|"
    r"cocktail|reception|party)\b|晚宴|周年大會|聯歡|酒會|嘉年華",
    re.I,
)
CANCELLED_RE = re.compile(
    r"活動取消|已經取消|經已取消|將取消|研討會將取消|"
    r"\bcancell?ed\b|\bthis (?:event|webinar|seminar) has been cancell?ed\b",
    re.I,
)
FREE_RE = re.compile(r"\b(?:free|complimentary|no charge|at no cost)\b|免費|豁免收費", re.I)
PAID_RE = re.compile(
    r"(?:HK\$|USD|\$|港幣|收費|費用|參加費)\s*\d|\b(?:fee|tuition|paid event)\b\s*[:：]?\s*(?:HK\$|USD|\$)?\s*\d",
    re.I,
)
GENERIC_TITLES = frozenset({
    "webinar", "event", "newsletter", "seminar", "workshop", "course",
    "活動", "研討會", "講座", "課程", "通訊", "click here", "詳情",
})

CPD_HOURS_RE = re.compile(
    r"(?:CPD\s*(?:hours?|hrs?|學時)?|持續專業發展)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|小時|學時)?|"
    r"可獲\s*(\d+(?:\.\d+)?)\s*(?:個)?\s*(?:CPD\s*)?(?:小時|學時)|"
    r"(\d+(?:\.\d+)?)\s*(?:個)?\s*CPD\s*(?:hours?|hrs?|小時|學時)",
    re.I,
)
DURATION_RE = re.compile(
    r"(?:duration|為時|時長|活動時數)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|小時)",
    re.I,
)
ZH_DATE_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
ZH_TIME_RANGE_RE = re.compile(
    r"(上午|下午|早上|晚上)?\s*(\d{1,2})\s*時\s*(?:(\d{1,2})\s*分)?\s*"
    r"(?:至|到|-|–|—)\s*"
    r"(上午|下午|早上|晚上)?\s*(\d{1,2})\s*時\s*(?:(\d{1,2})\s*分)?",
)
EN_TIME_AT_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",
    re.I,
)

UNSUBSCRIBE_RE = re.compile(
    r"unsubscribe|取消訂閱|退訂|若不想再收|不想再收取|you (?:have )?received this (?:email|newsletter)|"
    r"to stop receiving|manage (?:your )?preferences|opt[-\s]?out",
    re.I,
)


def clean_url(url: str) -> Optional[str]:
    """Strip tracking and personalization query params. Keep the destination itself."""
    if not url or not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw:
        return None
    # Drop mailto / javascript / cid
    low = raw.lower()
    if low.startswith(("mailto:", "javascript:", "cid:", "data:")):
        return None
    # Allow protocol-relative
    if raw.startswith("//"):
        raw = "https:" + raw
    try:
        parts = urlparse(raw)
    except Exception:
        return None
    if parts.scheme and parts.scheme not in ("http", "https"):
        return None
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        if TRACKING_PARAM_RE.match(key) or PERSONALIZATION_PARAM_RE.match(key):
            continue
        query.append((key, value))
    # Drop fragments that are only tracking; keep Zoom's #/registration UI fragment
    fragment = parts.fragment
    if fragment and TRACKING_PARAM_RE.match(fragment.split("=")[0]):
        fragment = ""
    cleaned = urlunparse((
        parts.scheme,
        parts.netloc,
        parts.path,
        parts.params,
        urlencode(query, doseq=True),
        fragment,
    ))
    return cleaned or None


def canonical_registration_url(url: Optional[str]) -> Optional[str]:
    """Stable key for Zoom/GForms destinations (no query, no fragment)."""
    cleaned = clean_url(url or "")
    if not cleaned:
        return None
    parts = urlparse(cleaned)
    path = parts.path.rstrip("/")
    return urlunparse((parts.scheme, parts.netloc.lower(), path, "", "", ""))


def classify_registration_url(url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return (mechanism, cleaned_url). Ordinary Zoom join links are not registration."""
    cleaned = clean_url(url or "")
    if not cleaned:
        return None, None
    if ZOOM_JOIN_RE.search(cleaned) and not (
        ZOOM_WEBINAR_RE.search(cleaned) or ZOOM_MEETING_RE.search(cleaned)
    ):
        return None, None
    if ZOOM_WEBINAR_RE.search(cleaned):
        return MECH_ZOOM_WEBINAR, cleaned
    if ZOOM_MEETING_RE.search(cleaned):
        return MECH_ZOOM_MEETING, cleaned
    if GFORM_RE.search(cleaned):
        return MECH_GOOGLE_FORMS, cleaned
    if MSFORM_RE.search(cleaned):
        return MECH_MICROSOFT_FORMS, cleaned
    if EVENTBRITE_RE.search(cleaned):
        return MECH_EVENTBRITE, cleaned
    if CIC_EVENT_RE.search(cleaned) and re.search(
        r"event|detail|eform|regform|register|enrol|workshop", cleaned, re.I
    ):
        return MECH_CIC_DETAIL, cleaned
    if CIC_EVENT_RE.search(cleaned):
        return MECH_CIC_DETAIL, cleaned
    if re.search(r"register|enrol|signup|sign-up|報名", cleaned, re.I):
        return MECH_OTHER, cleaned
    return None, cleaned


def is_legitimate_destination(mechanism: Optional[str], url: Optional[str]) -> bool:
    if not url:
        return False
    if mechanism in (
        MECH_ZOOM_WEBINAR,
        MECH_ZOOM_MEETING,
        MECH_GOOGLE_FORMS,
        MECH_MICROSOFT_FORMS,
        MECH_EVENTBRITE,
        MECH_CIC_DETAIL,
    ):
        return True
    if mechanism == MECH_OTHER and CIC_EVENT_RE.search(url or ""):
        return True
    return False


def parse_zh_date(text: str) -> Optional[str]:
    if not text:
        return None
    m = ZH_DATE_RE.search(text)
    if not m:
        return None
    try:
        import datetime as dt
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except Exception:
        return None


def parse_any_date(text: str) -> Optional[str]:
    if not text:
        return None
    return parse_zh_date(text) or parse_date(text)


def _zh_hour(h: int, minute: int, ap: str, peer_ap: str) -> Optional[str]:
    ap = (ap or peer_ap or "").strip()
    if ap in ("下午", "晚上") and h < 12:
        h += 12
    if ap in ("上午", "早上") and h == 12:
        h = 0
    if 0 <= h <= 23 and 0 <= minute <= 59:
        return f"{h:02d}:{minute:02d}"
    return None


def parse_zh_time_range(text: str) -> Optional[Tuple[str, str]]:
    if not text:
        return None
    m = ZH_TIME_RANGE_RE.search(text)
    if not m:
        return None
    sap, sh, sm, eap, eh, em = m.groups()
    start = _zh_hour(int(sh), int(sm or 0), sap or "", eap or "")
    end = _zh_hour(int(eh), int(em or 0), eap or "", sap or "")
    if start and end:
        return start, end
    return None


def parse_any_time_range(text: str) -> Optional[Tuple[str, str]]:
    if not text:
        return None
    zh = parse_zh_time_range(text)
    if zh:
        return zh
    # Try labelled or dashed English ranges inside a longer line
    compact = re.sub(r"\s+", " ", text)
    for chunk in re.split(r"[\n;|]", compact):
        chunk = chunk.strip()
        tr = parse_time_range(chunk)
        if tr:
            return tr
        m = re.search(
            r"(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)\s*[-–—至到]\s*"
            r"(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)",
            chunk,
            re.I,
        )
        if m:
            tr = parse_time_range(f"{m.group(1)}-{m.group(2)}")
            if tr:
                return tr
    return None


def extract_explicit_cpd_hours(text: str) -> Optional[float]:
    if not text:
        return None
    # Prefer clearly labelled CPD hours over a bare "N hours"
    m = CPD_HOURS_RE.search(text)
    if m:
        for g in m.groups():
            if g:
                try:
                    v = float(g)
                    if 0 < v < 50:
                        return v
                except ValueError:
                    pass
    # fetch.stated_cpd_hours only matches a whole string
    for line in re.split(r"[\n/|;]", text):
        v = stated_cpd_hours(line.strip())
        if v is not None:
            return v
    return None


def extract_explicit_duration(text: str) -> Optional[float]:
    if not text:
        return None
    m = DURATION_RE.search(text)
    if m:
        try:
            v = float(m.group(1))
            if 0 < v < 50:
                return v
        except ValueError:
            pass
    return None


def split_bilingual_title(title: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (display, title_zh, title_en) without inventing either side."""
    t = re.sub(r"\s+", " ", (title or "")).strip()
    t = re.sub(r"^\[活動取消\]\s*", "", t).strip()
    if not t:
        return "", None, None
    has_zh = bool(re.search(r"[\u4e00-\u9fff]", t))
    has_en = bool(re.search(r"[A-Za-z]{3,}", t))
    if has_zh and has_en:
        # Common CIC pattern: Chinese then English
        m = re.search(
            r"^(.*[\u4e00-\u9fff].*?)(?:\s+[–—-]\s+|\s{2,}|\s+)((?:Life First|[A-Z]|Webinar|Seminar).+)$",
            t,
        )
        if not m:
            # Split at first substantial English run after Chinese
            m = re.search(r"^(.*[\u4e00-\u9fff][^A-Za-z]*?)\s+([A-Za-z].+)$", t)
        if m:
            zh, en = m.group(1).strip(" –—-"), m.group(2).strip(" –—-")
            if zh and en and re.search(r"[\u4e00-\u9fff]", zh) and re.search(r"[A-Za-z]{3,}", en):
                return t, zh, en
        return t, t, t
    if has_zh:
        return t, t, None
    return t, None, t


def classify_type_and_civil(*texts: str) -> Tuple[str, bool, List[str]]:
    blob = " ".join(t for t in texts if t)
    typ = classify_rule(blob) if blob else "Technical"
    if HS_TOPIC_RE.search(blob):
        typ = "H&S"
    civil = bool(CIVIL_SAFETY_RE.search(blob))
    discs = ["Civil"] if civil else ["General"]
    return typ, civil, discs


def infer_attendance_mode(*texts: str, explicit: Optional[str] = None) -> str:
    if isinstance(explicit, str) and explicit.strip().upper() in event_mode.VALID:
        return explicit.strip().upper()
    ev = {
        "name": texts[0] if texts else "",
        "title": texts[0] if texts else "",
        "description": " ".join(t for t in texts if t),
    }
    return infer_mode(ev)["mode"]


def looks_social(title: str, description: str = "") -> bool:
    return bool(SOCIAL_RE.search(title or "")) or bool(
        SOCIAL_RE.search((description or "")[:400]) and not re.search(
            r"seminar|webinar|workshop|研討|講座|課程", title or "", re.I
        )
    )


def looks_cancelled(*texts: str) -> bool:
    return any(CANCELLED_RE.search(t or "") for t in texts)


def infer_fee(*texts: str) -> Optional[bool]:
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    if FREE_RE.search(blob) and not PAID_RE.search(blob):
        return True
    if PAID_RE.search(blob):
        return False
    return None


def is_future_date(date_iso: Optional[str], today=None) -> bool:
    if not date_iso:
        return False
    import datetime as dt
    today = today or TODAY
    try:
        d = dt.date.fromisoformat(str(date_iso)[:10])
    except Exception:
        return False
    return today <= d <= today + dt.timedelta(days=KEEP_DAYS_AHEAD)


def title_is_clean(title: str) -> bool:
    t = strip_page_chrome(title or "")
    if not t or not is_good_title(t):
        return False
    if t.lower().strip() in GENERIC_TITLES:
        return False
    if len(t) < 8:
        return False
    return True


def _gate(passed: bool, reason: str = "") -> Dict[str, Any]:
    out = {"pass": bool(passed)}
    if reason:
        out["reason"] = reason
    return out


def apply_quality_gates(candidate: Dict[str, Any], *, trusted: bool) -> Dict[str, Any]:
    """Stamp pilot_status and gates A–I. Uncertain candidates never become eligible."""
    title = candidate.get("title") or ""
    date = candidate.get("date")
    typ = candidate.get("type")
    mech = (candidate.get("registration") or {}).get("mechanism")
    dest = (candidate.get("registration") or {}).get("destination")
    status = (candidate.get("registration") or {}).get("status")
    free = candidate.get("free")
    cancelled = bool(candidate.get("cancelled"))

    gates = {}
    gates["A"] = _gate(trusted, "trusted_sender" if trusted else "untrusted_sender")
    professional = bool(title) and (
        typ in ("H&S", "Technical", "GPM")
        or bool(re.search(r"webinar|seminar|workshop|研討|講座|課程|briefing|forum|conference", title, re.I))
        or bool(candidate.get("civil_related"))
    )
    gates["B"] = _gate(professional, "plausible_professional_event" if professional else "not_professional_event")
    gates["C"] = _gate(is_future_date(date), "valid_future_date" if is_future_date(date) else "missing_or_not_future_date")
    gates["D"] = _gate(title_is_clean(title), "clean_title" if title_is_clean(title) else (title_quality_reason(title) or "generic_or_bad_title"))
    legit = is_legitimate_destination(mech, dest)
    gates["E"] = _gate(legit, "legitimate_destination" if legit else "no_legitimate_registration_or_cic_url")
    not_closed = (status != "CLOSED") and not cancelled
    if cancelled:
        gates["F"] = _gate(False, "cancelled")
    elif status == "CLOSED":
        gates["F"] = _gate(False, "registration_closed")
    else:
        gates["F"] = _gate(True, "not_positively_closed")
    social = looks_social(title, candidate.get("description") or "")
    gates["G"] = _gate(not social, "social_only" if social else "not_social")
    # Free-first: an explicit fee is excluded for CIC (not an accept_paid source).
    # Unknown / free pass. Explicit free=False fails.
    paid_excluded = free is False
    gates["H"] = _gate(not paid_excluded, "explicit_fee_excluded_by_free_first" if paid_excluded else "no_excluding_fee")
    # Confidence: do not invent details. Need a real title and either a verified
    # date or we refuse eligibility. Hours may be unknown.
    invented = bool(candidate.get("_invented"))
    has_core = bool(title_is_clean(title)) and not invented
    conf = candidate.get("confidence") or "LOW"
    sufficient = has_core and date and conf in ("HIGH", "MEDIUM") and not invented
    if not date:
        sufficient = False
        reason_i = "no_date_cannot_invent"
    elif invented:
        sufficient = False
        reason_i = "invented_details"
    elif conf == "LOW":
        sufficient = False
        reason_i = "low_confidence"
    else:
        reason_i = "sufficient"
    gates["I"] = _gate(sufficient, reason_i)

    failures = [k for k, v in gates.items() if not v["pass"]]
    if failures:
        # Untrusted, closed, cancelled, social, paid, malformed/bad title → rejected
        hard = set()
        if not gates["A"]["pass"]:
            hard.add("A")
        if not gates["F"]["pass"]:
            hard.add("F")
        if not gates["G"]["pass"]:
            hard.add("G")
        if not gates["H"]["pass"]:
            hard.add("H")
        if not gates["D"]["pass"] and not title:
            hard.add("D")
        if hard.intersection(failures) and (not gates["A"]["pass"] or cancelled or status == "CLOSED" or social or paid_excluded):
            pilot_status = STATUS_REJECTED
        elif not professional and not title:
            pilot_status = STATUS_REJECTED
        else:
            # Missing date, uncertain destination, weak confidence → review
            pilot_status = STATUS_REVIEW
            if not gates["A"]["pass"]:
                pilot_status = STATUS_REJECTED
    else:
        pilot_status = STATUS_ELIGIBLE

    candidate["gates"] = gates
    candidate["gate_failures"] = failures
    candidate["pilot_status"] = pilot_status
    return candidate


def set_hours(candidate: Dict[str, Any], texts: Iterable[str]) -> Dict[str, Any]:
    """Priority: explicit CPD hours, explicit duration, start/end estimate, unknown."""
    blob = "\n".join(t for t in texts if t)
    explicit = extract_explicit_cpd_hours(blob)
    if explicit is not None:
        candidate["hrs"] = explicit
        candidate["hrs_est"] = False
        return candidate
    duration = extract_explicit_duration(blob)
    if duration is not None:
        candidate["hrs"] = duration
        candidate["hrs_est"] = True
        return candidate
    start, end = candidate.get("start_time"), candidate.get("end_time")
    if start and end:
        est = hours_from_range(start, end)
        if est is not None:
            candidate["hrs"] = est
            candidate["hrs_est"] = True
            return candidate
    candidate.setdefault("hrs", None)
    candidate.setdefault("hrs_est", False)
    return candidate


def destination_title_mismatch(newsletter_title: str, dest_title: str) -> bool:
    """Material topic mismatch (cancellation prefixes are ignored)."""
    a = re.sub(r"^\[活動取消\]\s*", "", newsletter_title or "").strip()
    b = re.sub(r"^\[活動取消\]\s*", "", dest_title or "").strip()
    if not a or not b:
        return False
    sim = _title_sim(a, b)
    return sim < 0.50


def compare_to_production(
    candidate: Dict[str, Any],
    production_events: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Read-only frozen-threshold compare. Does not modify production events.

    Global dedup thresholds are unchanged. The pilot additionally treats an
    identical cleaned registration destination as a strong signal, so the same
    Life First / safety talk can be merged across CIC, OSHC, Labour, Zoom, etc.
    """
    result = {
        "is_duplicate": False,
        "matched_id": None,
        "matched_source": None,
        "matched_name": None,
        "matched_date": None,
        "title_similarity": None,
        "merge": None,
    }
    if not production_events:
        candidate["duplicate"] = result
        return candidate

    name = candidate.get("title") or ""
    date = candidate.get("date")
    dest = canonical_registration_url((candidate.get("registration") or {}).get("destination"))
    best = None
    best_sim = 0.0
    for ev in production_events:
        if not isinstance(ev, dict):
            continue
        ev_date = ev.get("date")
        if date and ev_date and date != ev_date:
            continue
        # If the newsletter has no date, only match on destination or identical URL.
        ev_url = canonical_registration_url(ev.get("url") or "")
        ev_dest = canonical_registration_url(
            ((ev.get("registration") or {}) if isinstance(ev.get("registration"), dict) else {}).get("destination")
            or ev.get("url")
            or ""
        )
        same_dest = bool(dest and ev_dest and dest == ev_dest)
        same_url = bool(dest and ev_url and dest == ev_url)
        sim = _title_sim(name, ev.get("name") or ev.get("title") or "")
        if date and ev_date and date == ev_date and sim >= 0.90:
            probe_a = {
                "name": name,
                "url": dest or candidate.get("url") or "",
                "time": candidate.get("time") or "",
                "hrs": candidate.get("hrs"),
                "hrs_est": candidate.get("hrs_est"),
            }
            probe_b = {
                "name": ev.get("name") or ev.get("title") or "",
                "url": ev.get("url") or "",
                "time": ev.get("time") or "",
                "hrs": ev.get("hrs"),
                "hrs_est": ev.get("hrs_est"),
            }
            strong = _strong_signal(probe_a, probe_b) or same_dest or same_url or sim >= 0.97
            if not strong:
                continue
        elif same_dest or same_url:
            pass
        else:
            continue
        if sim >= best_sim or same_dest or same_url:
            best_sim = max(sim, best_sim)
            best = ev
            if same_dest or same_url:
                break
    if best:
        result["is_duplicate"] = True
        result["matched_id"] = best.get("id")
        result["matched_source"] = best.get("source") or best.get("group")
        result["matched_name"] = best.get("name")
        result["matched_date"] = best.get("date")
        result["title_similarity"] = round(best_sim, 3)
        result["merge"] = merge_metadata(best, candidate)
    candidate["duplicate"] = result
    return candidate


def merge_metadata(official: Dict[str, Any], newsletter: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded best-evidence recommendation. Not written to events.json.

    Prefer official source title and date; keep explicit start/end, mode, CPD
    hours, and the best registration destination from either side.
    """
    rec = {
        "id": official.get("id"),
        "title": official.get("name") or official.get("title") or newsletter.get("title"),
        "date": official.get("date") or newsletter.get("date"),
        "source_kept": official.get("source"),
        "newsletter_provenance": {
            "discovery": DISCOVERY,
            "source": SOURCE_NAME,
            "organisation": ORGANISATION,
        },
    }
    off_time = official.get("time") or ""
    news_time = newsletter.get("time") or ""
    if official.get("start_time") and official.get("end_time"):
        rec["time"] = f"{official['start_time']}-{official['end_time']}"
    elif re.match(r"\d{2}:\d{2}-\d{2}:\d{2}$", off_time or ""):
        rec["time"] = off_time
    elif news_time:
        rec["time"] = news_time
    else:
        rec["time"] = off_time or news_time
    off_mode = official.get("mode")
    news_mode = newsletter.get("mode")
    if off_mode and off_mode != event_mode.MODE_UNKNOWN:
        rec["mode"] = off_mode
    elif news_mode and news_mode != event_mode.MODE_UNKNOWN:
        rec["mode"] = news_mode
    else:
        rec["mode"] = off_mode or news_mode
    if official.get("hrs") is not None and not official.get("hrs_est"):
        rec["hrs"] = official.get("hrs")
        rec["hrs_est"] = False
    elif newsletter.get("hrs") is not None and not newsletter.get("hrs_est"):
        rec["hrs"] = newsletter.get("hrs")
        rec["hrs_est"] = False
    elif official.get("hrs") is not None:
        rec["hrs"] = official.get("hrs")
        rec["hrs_est"] = official.get("hrs_est")
    elif newsletter.get("hrs") is not None:
        rec["hrs"] = newsletter.get("hrs")
        rec["hrs_est"] = newsletter.get("hrs_est")
    off_reg = official.get("registration") if isinstance(official.get("registration"), dict) else {}
    news_reg = newsletter.get("registration") if isinstance(newsletter.get("registration"), dict) else {}
    rec["registration"] = _best_registration(off_reg, news_reg)
    return rec


def _best_registration(official: Dict[str, Any], newsletter: Dict[str, Any]) -> Dict[str, Any]:
    preferred = (
        MECH_ZOOM_WEBINAR,
        MECH_ZOOM_MEETING,
        MECH_GOOGLE_FORMS,
        MECH_MICROSOFT_FORMS,
        MECH_EVENTBRITE,
        "OSHC_PORTAL",
        "CIC_PORTAL",
        MECH_CIC_DETAIL,
    )
    def rank(reg):
        dest = (reg or {}).get("destination")
        mech = (reg or {}).get("mechanism")
        if not dest:
            return -1
        try:
            return len(preferred) - preferred.index(mech)
        except ValueError:
            return 0
    # Prefer a non-closed official dest; otherwise the better mechanism.
    off_status = (official or {}).get("status")
    news_status = (newsletter or {}).get("status")
    if (official or {}).get("destination") and off_status != "CLOSED":
        if rank(official) >= rank(newsletter) or not (newsletter or {}).get("destination"):
            return {k: official.get(k) for k in ("mechanism", "destination", "status") if k in official}
    if (newsletter or {}).get("destination") and news_status != "CLOSED":
        return {k: newsletter.get(k) for k in ("mechanism", "destination", "status") if k in newsletter}
    if (official or {}).get("destination"):
        return {k: official.get(k) for k in ("mechanism", "destination", "status") if k in official}
    return {k: newsletter.get(k) for k in ("mechanism", "destination", "status") if k in (newsletter or {})}


def confidence_for(candidate: Dict[str, Any], trusted: bool) -> str:
    if not trusted:
        return "LOW"
    title_ok = title_is_clean(candidate.get("title") or "")
    date_ok = bool(candidate.get("date"))
    dest_ok = is_legitimate_destination(
        (candidate.get("registration") or {}).get("mechanism"),
        (candidate.get("registration") or {}).get("destination"),
    )
    if title_ok and date_ok and dest_ok:
        return "HIGH"
    if title_ok and (date_ok or dest_ok):
        return "MEDIUM"
    return "LOW"


def public_candidate_view(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Report shape: event content and provenance only. No subscriber PII."""
    reg = candidate.get("registration") or {}
    dup = candidate.get("duplicate") or {}
    return {
        "title": candidate.get("title"),
        "title_zh": candidate.get("title_zh"),
        "title_en": candidate.get("title_en"),
        "date": candidate.get("date"),
        "time": candidate.get("time") or "",
        "start_time": candidate.get("start_time"),
        "end_time": candidate.get("end_time"),
        "mode": candidate.get("mode"),
        "type": candidate.get("type"),
        "civil_related": bool(candidate.get("civil_related")),
        "hrs": candidate.get("hrs"),
        "hrs_est": bool(candidate.get("hrs_est")),
        "free": candidate.get("free"),
        "registration_mechanism": reg.get("mechanism"),
        "registration_status": reg.get("status"),
        "registration_destination": reg.get("destination"),
        "duplicate_status": "duplicate" if dup.get("is_duplicate") else "unique_newsletter_only",
        "matched_source": dup.get("matched_source"),
        "confidence": candidate.get("confidence"),
        "pilot_status": candidate.get("pilot_status"),
        "gate_failures": candidate.get("gate_failures") or [],
        "cancelled": bool(candidate.get("cancelled")),
        "discovery": DISCOVERY,
        "source": SOURCE_NAME,
        "organisation": ORGANISATION,
    }
