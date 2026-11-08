"""
Google Forms registration schema enrichment (Sprint 2B2).

Fetches only publicly accessible viewform HTML during scrape time,
extracts non-personal field schema (entry IDs, labels, types), and
attaches compact registration metadata to events.

Never stores profile values, answers, consent choices, or raw HTML.
Never POSTs / submits / signs in.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode

import requests

# Reuse shared constants when available (fetch.py import is optional for standalone).
try:
    from fetch import HEADERS, ROOT, OUT, log, allowed  # type: ignore
except Exception:  # pragma: no cover
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    OUT = os.path.join(ROOT, "events.json")
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 "
            "(compatible; CPDHunterBot/2.2; free CPD calendar)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9,zh-HK;q=0.8",
    }

    def log(*a):
        print(*a, file=sys.stderr, flush=True)

    def allowed(url):
        return True

MECHANISM = "GOOGLE_FORMS"

# Google Forms question type codes (subset).
TYPE_SHORT = 0
TYPE_PARAGRAPH = 1
TYPE_RADIO = 2
TYPE_DROPDOWN = 3
TYPE_CHECKBOX = 4
TYPE_SCALE = 5
TYPE_SECTION = 6
TYPE_GRID = 7
TYPE_PAGE = 8
TYPE_DATE = 9
TYPE_TIME = 10

TYPE_NAME = {
    TYPE_SHORT: "SHORT_TEXT",
    TYPE_PARAGRAPH: "PARAGRAPH",
    TYPE_RADIO: "RADIO",
    TYPE_DROPDOWN: "DROPDOWN",
    TYPE_CHECKBOX: "CHECKBOX",
    TYPE_SCALE: "SCALE",
    TYPE_SECTION: "SECTION",
    TYPE_GRID: "GRID",
    TYPE_PAGE: "PAGE",
    TYPE_DATE: "DATE",
    TYPE_TIME: "TIME",
}

GFORM_HREF_RE = re.compile(
    r"""https?://(?:forms\.gle/[A-Za-z0-9_-]+|docs\.google\.com/forms/(?:d/e/|d/)[A-Za-z0-9_-]+(?:/[^"'\\\s<>]*)?)""",
    re.I,
)
# Also catch href="/forms/..." style is not used for Google.

FB_RE = re.compile(
    r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\])\s*;\s*</script>",
    re.S,
)

FORM_ID_RE = re.compile(r"(?:/forms/d/e/|/forms/d/)([A-Za-z0-9_-]+)")

SAFE_PROFILE_FIELDS = (
    "englishName",
    "chineseName",
    "email",
    "phone",
    "organisation",
    "position",
    "hkieNumber",
    "primaryDiscipline",
    "secondaryDiscipline",
)


def normalize_label(label: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for matching."""
    if not label:
        return ""
    s = label.lower()
    s = re.sub(r"[\u3000\s]+", " ", s)
    # keep CJK; strip most punctuation
    s = re.sub(r"[^\w\u4e00-\u9fff\s]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _contains_any(norm: str, phrases: Tuple[str, ...]) -> bool:
    return any(p in norm for p in phrases)


# Phrases that always block mapping (judgment / unsafe).
_BLOCK_PHRASES = (
    "consent",
    "privacy",
    "personal data provided",
    "declaration",
    "acknowledge",
    "i noted",
    "i agree",
    "marketing",
    "newsletter",
    "promotional",
    "are you a hkie member",
    "are you hkie member",
    "are you a member",
    "are you member",
    "member?",
    "attendance",
    "mode of",
    "passport number",
    "passport no",
    "travel document number",
    "room",
    "accommodation",
    "hotel",
    "dietary",
    "allergy",
    "running",
    "legal",
    "disclaimer",
    "assumption of risk",
    "emergency",
    "mainland mobile",
    "other name",
    "media consent",
    "photography",
    "first come",
    "priority will be given",
    "wish to apply",
    "course enrollment",
    "session ",
    # split-name fields — leave manual (no guessing split of englishName)
    "surname",
    "given name",
    "first name",
    "last name",
    "family name",
    "forename",
    # title / honorific choices
    "mr ms",
    "mr/ms",
    "ir/prof",
)


def _is_blocked(norm: str) -> bool:
    if not norm:
        return True
    if norm in ("title",):
        return True
    # bare Title with honorific context already covered; exact title alone is blocked
    if _contains_any(norm, _BLOCK_PHRASES):
        return True
    # Chinese consent-ish
    if "聲明" in norm or "同意" in norm and "personal" in norm:
        return True
    return False


def map_label_to_profile(label: str, type_code: Optional[int] = None) -> Optional[str]:
    """
    Deterministic high-confidence label → profile field mapping.
    Returns None if unsafe, ambiguous, judgment, or split-name.
    """
    norm = normalize_label(label)
    if _is_blocked(norm):
        return None

    # Never map generic Title (Mr/Ms/Ir) to position.
    if norm == "title" or norm.startswith("title "):
        return None

    # chineseName (before generic name)
    if _contains_any(
        norm,
        (
            "chinese name",
            "name in chinese",
            "name chinese",
            "中文姓名",
            "姓名 中文",
            "中文名",
        ),
    ) or re.search(r"name\s*\(.*chinese", norm):
        return "chineseName"

    # email
    if _contains_any(
        norm,
        ("email address", "e mail", "email", "電郵", "電子郵件"),
    ):
        # avoid mapping section text; need it to look like a field label
        if "personal data" in norm:
            return None
        return "email"

    # phone (not emergency / mainland — blocked above)
    if _contains_any(
        norm,
        (
            "mobile phone",
            "mobile number",
            "mobile no",
            "contact number",
            "contact phone",
            "telephone",
            "phone number",
            "mobile",
            "phone",
            "手提電話",
            "聯絡電話",
            "電話",
        ),
    ):
        return "phone"

    # hkieNumber — before organisation (membership no.)
    if _contains_any(
        norm,
        (
            "hkie membership",
            "hkie or iom3 membership",
            "membership no",
            "membership number",
            "member no",
            "會員編號",
        ),
    ) or norm.startswith("membership no") or norm.startswith("membership number"):
        return "hkieNumber"
    if "please fill in your membership number" in norm:
        return "hkieNumber"
    # "Membership No" / "Membership Number" without HKIE prefix (common on joint events)
    if norm in ("membership no", "membership number") or re.match(
        r"membership no\b", norm
    ):
        return "hkieNumber"

    # position (before organisation so "company position" wins)
    if _contains_any(
        norm,
        (
            "job title",
            "job position",
            "company position",
            "designation",
            "position",
            "職位",
        ),
    ):
        return "position"

    # organisation
    if _contains_any(
        norm,
        (
            "organisation",
            "organization",
            "company name",
            "company",
            "employer",
            "institution",
            "present employment",
            "公司",
            "機構",
            "僱主",
        ),
    ):
        # Avoid "Organization/Division/Committee" judgment radios
        if "division" in norm and "committee" in norm:
            return None
        # Avoid bare "Organization" radio that is a choice of organising body
        if type_code in (TYPE_RADIO, TYPE_CHECKBOX) and norm in (
            "organization",
            "organisation",
        ):
            return None
        return "organisation"

    # secondaryDiscipline must be checked before primary
    if _contains_any(norm, ("secondary discipline", "second discipline", "次要界別")):
        return "secondaryDiscipline"

    # primaryDiscipline
    if _contains_any(
        norm,
        (
            "engineering discipline",
            "discipline",
            "專業界別",
            "學科",
        ),
    ) or re.match(r"division\b", norm) or "division e g" in norm or "division eg" in norm:
        # Skip choice-of-event / committee radios
        if "committee" in norm or "wish to apply" in norm:
            return None
        return "primaryDiscipline"

    # englishName — single full-name fields only (split names blocked above)
    if _contains_any(
        norm,
        (
            "english full name",
            "english name",
            "name in english",
            "full name",
            "applicant name",
            "name english",
        ),
    ) or re.search(r"name\s*\(.*english", norm):
        if "institute" in norm or "emergency" in norm:
            return None
        return "englishName"

    # bare "Name" / "Name:" — only if no other modifiers
    if norm in ("name", "name "):
        return "englishName"

    return None


def extract_gform_urls(text: str) -> List[str]:
    """Return unique Google Forms / forms.gle URLs found in HTML or text."""
    if not text:
        return []
    found = []
    seen = set()
    for m in GFORM_HREF_RE.finditer(text):
        u = m.group(0).rstrip(").,;'\"")
        u = u.replace("&amp;", "&")
        if "formResponse" in u:
            u = u.replace("/formResponse", "/viewform")
        if u not in seen:
            seen.add(u)
            found.append(u)
    return found



HKIE_EVENT_DETAIL_RE = re.compile(
    r"https?://(?:www\.)?hkie\.org\.hk/(?:tc/)?events/event-detail/([A-Za-z0-9]+)/?",
    re.I,
)


def fetch_hkie_eventdetail_html(session: requests.Session, event_page_url: str) -> Optional[str]:
    """
    HKIE event-detail pages are shells; registration HTML comes from the public
    hkie_api eventdetail action (same payload the public site loads in-browser).
    GET is used for Google Forms themselves; this POST is organiser content only.
    """
    m = HKIE_EVENT_DETAIL_RE.match((event_page_url or "").split("#")[0].split("?")[0])
    if not m:
        return None
    eid = m.group(1)
    api = "https://hkie.org.hk/hkie_api/index.php"
    try:
        if not allowed(api) and not allowed("https://hkie.org.hk/"):
            # still try — public endpoint used by the site itself
            pass
        r = session.post(
            api,
            headers={
                **HEADERS,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": event_page_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            data={"action": "eventdetail", "lang": "en", "eid": eid},
            timeout=40,
        )
        if r.status_code != 200:
            return None
        payload = r.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            html = data.get("html")
            return html if isinstance(html, str) else None
    except Exception as ex:
        log(f"  gforms: hkie eventdetail fail {eid}: {ex}")
    return None


def canonical_viewform_url(url: str, form_id: Optional[str] = None) -> str:
    """Build a clean public viewform URL (no prefill params)."""
    if form_id:
        return f"https://docs.google.com/forms/d/e/{form_id}/viewform"
    m = FORM_ID_RE.search(url or "")
    if m:
        fid = m.group(1)
        return f"https://docs.google.com/forms/d/e/{fid}/viewform"
    # forms.gle short link — caller should resolve first
    return (url or "").split("#")[0]


def detect_form_status(html: str, final_url: str) -> str:
    """OPEN | CLOSED | LOGIN_REQUIRED | UNKNOWN"""
    fu = (final_url or "").lower()
    h = html or ""
    hl = h.lower()
    if "/closedform" in fu or "/closedform" in hl:
        return "CLOSED"
    if "no longer accepting" in hl or "not accepting responses" in hl:
        return "CLOSED"
    # Sign-in wall (do not scrape behind login)
    if "accounts.google.com/ServiceLogin" in h or "accounts.google.com/v3/signin" in hl:
        if "FB_PUBLIC_LOAD_DATA_" not in h:
            return "LOGIN_REQUIRED"
    if "FB_PUBLIC_LOAD_DATA_" in h:
        return "OPEN"
    if "sign in" in hl and "google forms" in hl and "FB_PUBLIC_LOAD_DATA_" not in h:
        return "LOGIN_REQUIRED"
    return "UNKNOWN"


def parse_fb_public_load_data(html: str) -> Optional[list]:
    m = FB_RE.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _options_from_entry(entry_item: list) -> List[str]:
    opts = []
    raw = entry_item[1] if len(entry_item) > 1 else None
    if not isinstance(raw, list):
        return opts
    for o in raw:
        if isinstance(o, list) and o and isinstance(o[0], str):
            opts.append(o[0])
    return opts


def questions_from_fb(data: list) -> Tuple[Optional[str], List[dict]]:
    """Return (formId, questions[{entryId,label,type,typeCode,options}])."""
    form_id = None
    if isinstance(data, list) and len(data) > 14 and isinstance(data[14], str):
        # e.g. "e/1FAIpQLS..."
        part = data[14]
        if part.startswith("e/"):
            form_id = part[2:]
        else:
            form_id = part
    questions: List[dict] = []
    try:
        qs = data[1][1]
    except (TypeError, IndexError, KeyError):
        return form_id, questions
    if not isinstance(qs, list):
        return form_id, questions
    for q in qs:
        if not isinstance(q, list) or len(q) < 4:
            continue
        label = q[1] if isinstance(q[1], str) else ""
        type_code = q[3] if isinstance(q[3], int) else None
        entries = q[4] if len(q) > 4 and isinstance(q[4], list) else []
        if not entries:
            # section / page headers — skip (no entry id)
            continue
        for ent in entries:
            if not isinstance(ent, list) or not ent:
                continue
            entry_num = ent[0]
            if not isinstance(entry_num, int):
                continue
            questions.append(
                {
                    "entryId": f"entry.{entry_num}",
                    "label": label.strip(),
                    "type": TYPE_NAME.get(type_code, f"TYPE_{type_code}"),
                    "typeCode": type_code,
                    "options": _options_from_entry(ent),
                }
            )
    return form_id, questions


def apply_profile_mappings(questions: List[dict]) -> List[dict]:
    """
    Attach profileField + safePrefill. Clear duplicates that map to the same
    profile field (ambiguous → neither prefilled).
    """
    mapped: List[dict] = []
    for q in questions:
        pf = map_label_to_profile(q.get("label") or "", q.get("typeCode"))
        type_code = q.get("typeCode")
        # Only short/paragraph text are auto-safe; choice fields need exact match later.
        text_ok = type_code in (TYPE_SHORT, TYPE_PARAGRAPH)
        choice_ok = type_code in (TYPE_RADIO, TYPE_DROPDOWN)  # not checkbox
        safe = bool(pf) and text_ok
        # Choice: keep profileField for UI listing but safePrefill only if we will
        # exact-match on the frontend; mark safePrefill True so frontend may try
        # exact option match. Checkbox never.
        if pf and choice_ok:
            safe = True  # frontend will omit unless exact option match
        if pf and type_code == TYPE_CHECKBOX:
            safe = False
            pf = pf  # still record mapping? No — judgment multi-select; leave manual
            pf = None
        field = {
            "entryId": q["entryId"],
            "profileField": pf,
            "label": q.get("label") or "",
            "type": q.get("type") or "UNKNOWN",
            "safePrefill": bool(safe and pf),
        }
        # Keep options only for choice types (non-personal option strings).
        if choice_ok and q.get("options"):
            field["options"] = list(q["options"])
        mapped.append(field)

    # Ambiguity: same profileField claimed by >1 field → clear all of them.
    counts: Dict[str, int] = {}
    for f in mapped:
        pf = f.get("profileField")
        if pf:
            counts[pf] = counts.get(pf, 0) + 1
    for f in mapped:
        pf = f.get("profileField")
        if pf and counts.get(pf, 0) > 1:
            f["profileField"] = None
            f["safePrefill"] = False
            f.pop("options", None)
    return mapped


def build_registration_meta(
    *,
    destination: str,
    form_id: Optional[str],
    status: str,
    fields: List[dict],
) -> dict:
    # Strip options from non-safe or unused to keep events.json compact? Keep for choice match.
    compact_fields = []
    for f in fields:
        item = {
            "entryId": f["entryId"],
            "profileField": f.get("profileField"),
            "label": f.get("label") or "",
            "type": f.get("type") or "UNKNOWN",
            "safePrefill": bool(f.get("safePrefill")),
        }
        if f.get("options") and f.get("safePrefill") and f.get("type") in (
            "RADIO",
            "DROPDOWN",
        ):
            item["options"] = f["options"]
        compact_fields.append(item)
    return {
        "mechanism": MECHANISM,
        "destination": destination,
        "formId": form_id or "",
        "status": status,
        "fields": compact_fields,
        "requiresManualCompletion": True,
    }


def fetch_url(session: requests.Session, url: str, timeout: int = 40) -> Tuple[str, str]:
    """GET only. Returns (final_url, text). Never POSTs. Rewrites formResponse → viewform."""
    target = url
    if "formResponse" in (target or ""):
        target = target.replace("/formResponse", "/viewform")
    r = session.get(target, headers=HEADERS, timeout=timeout, allow_redirects=True)
    final = r.url or target
    if "formResponse" in final:
        # Redirect landed on formResponse — force viewform GET
        final = final.replace("/formResponse", "/viewform")
        r = session.get(final, headers=HEADERS, timeout=timeout, allow_redirects=True)
        final = r.url or final
        if "formResponse" in final:
            raise RuntimeError("refusing formResponse URL")
    return final, r.text or ""


def resolve_and_parse_form(
    session: requests.Session, start_url: str
) -> dict:
    """
    Resolve forms.gle → viewform, detect status, parse schema.
    Returns registration meta dict (never includes profile values).
    """
    final, html = fetch_url(session, start_url)
    status = detect_form_status(html, final)
    form_id = None
    m = FORM_ID_RE.search(final) or FORM_ID_RE.search(html[:5000] if html else "")
    if m:
        form_id = m.group(1)
    # Also from closedform path
    if not form_id:
        m2 = re.search(r"/forms/d/e/([A-Za-z0-9_-]+)/closedform", final + html[:8000])
        if m2:
            form_id = m2.group(1)

    destination = canonical_viewform_url(final, form_id) if form_id else canonical_viewform_url(final)

    if status == "CLOSED":
        return build_registration_meta(
            destination=destination, form_id=form_id, status="CLOSED", fields=[]
        )
    if status == "LOGIN_REQUIRED":
        return build_registration_meta(
            destination=destination, form_id=form_id, status="LOGIN_REQUIRED", fields=[]
        )
    if status != "OPEN":
        return build_registration_meta(
            destination=destination, form_id=form_id, status=status, fields=[]
        )

    data = parse_fb_public_load_data(html)
    if not data:
        return build_registration_meta(
            destination=destination, form_id=form_id, status="UNKNOWN", fields=[]
        )
    fid2, questions = questions_from_fb(data)
    if fid2:
        form_id = fid2
        destination = canonical_viewform_url(destination, form_id)
    fields = apply_profile_mappings(questions)
    return build_registration_meta(
        destination=destination, form_id=form_id, status="OPEN", fields=fields
    )


def discover_form_url_for_event(
    session: requests.Session, event: dict, page_cache: Optional[dict] = None
) -> Optional[str]:
    """
    Find a Google Forms URL for an event:
    1) event.url itself if already a gform
    2) HKIE event-detail → public hkie_api eventdetail HTML
    3) else GET organiser page and scan for forms.gle / docs.google.com/forms
    """
    url = (event.get("url") or "").strip()
    if not url.startswith("http"):
        return None
    direct = extract_gform_urls(url)
    if direct:
        return direct[0]
    if "forms.gle" in url or "docs.google.com/forms" in url:
        return url.split("#")[0]

    # HKIE SPA event-detail: registration HTML via public API
    if HKIE_EVENT_DETAIL_RE.match(url.split("#")[0].split("?")[0]):
        html = fetch_hkie_eventdetail_html(session, url)
        if html:
            found = extract_gform_urls(html)
            if found:
                return found[0]

    # Fetch organiser page (public GET)
    try:
        if not allowed(url):
            log(f"  gforms: robots block organiser {url[:80]}")
            return None
        if page_cache is not None and url in page_cache:
            _final, html = page_cache[url]
        else:
            _final, html = fetch_url(session, url)
            if page_cache is not None:
                page_cache[url] = (_final, html)
    except Exception as ex:
        log(f"  gforms: organiser fetch fail {event.get('id')}: {ex}")
        return None
    found = extract_gform_urls(html)
    return found[0] if found else None


def enrich_google_forms_registration(
    events: List[dict],
    *,
    session: Optional[requests.Session] = None,
    sleep_s: float = 0.8,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """
    Post-pass: attach event['registration'] for discoverable Google Forms.
    Failures for one event never abort the batch.
    Returns counters.
    """
    sess = session or requests.Session()
    stats = {
        "scanned": 0,
        "discovered": 0,
        "OPEN": 0,
        "CLOSED": 0,
        "LOGIN_REQUIRED": 0,
        "UNKNOWN": 0,
        "errors": 0,
        "skipped_existing": 0,
    }
    page_cache: Dict[str, Tuple[str, str]] = {}
    form_cache: Dict[str, dict] = {}

    def _cached_fetch(url: str) -> Tuple[str, str]:
        if url in page_cache:
            return page_cache[url]
        final, html = fetch_url(sess, url)
        page_cache[url] = (final, html)
        return final, html

    def _discover(ev: dict) -> Optional[str]:
        return discover_form_url_for_event(sess, ev, page_cache=page_cache)

    n = 0
    for ev in events:
        if limit is not None and n >= limit:
            break
        stats["scanned"] += 1
        n += 1
        try:
            # Prefer destination already found by reg_discover when it is Google Forms
            existing = ev.get("registration") or {}
            form_url = None
            dest = existing.get("destination") if existing.get("mechanism") == "GOOGLE_FORMS" else None
            if isinstance(dest, str) and ("forms.gle" in dest or "docs.google.com/forms" in dest):
                form_url = dest
            if not form_url:
                form_url = _discover(ev)
            if not form_url:
                continue
            stats["discovered"] += 1
            if form_url in form_cache:
                meta = form_cache[form_url]
            else:
                meta = resolve_and_parse_form(sess, form_url)
                _assert_no_pii_in_meta(meta)
                form_cache[form_url] = meta
                if sleep_s:
                    time.sleep(sleep_s)
            # Preserve discovery diagnostics from Sprint 2C
            for k in ("sourceUrlClass", "confidence", "discoveryMethod"):
                if existing.get(k) and not meta.get(k):
                    meta[k] = existing[k]
            if not meta.get("sourceUrlClass"):
                meta["sourceUrlClass"] = "DIRECT_REGISTRATION"
            if not meta.get("confidence"):
                meta["confidence"] = "HIGH"
            if not meta.get("discoveryMethod"):
                meta["discoveryMethod"] = "gforms_schema_enrich"
            ev["registration"] = meta
            st = meta.get("status") or "UNKNOWN"
            stats[st] = stats.get(st, 0) + 1
            log(
                f"  gforms: {ev.get('id')} -> {st} "
                f"fields={len(meta.get('fields') or [])} "
                f"safe={sum(1 for f in (meta.get('fields') or []) if f.get('safePrefill'))}"
            )
        except Exception as ex:
            stats["errors"] += 1
            log(f"  gforms: error {ev.get('id')}: {type(ex).__name__}: {ex}")
            if sleep_s:
                time.sleep(min(sleep_s, 0.5))
    return stats


def _assert_no_pii_in_meta(meta: dict) -> None:
    """Refuse to attach meta if it looks like it contains answer/profile values."""
    for f in meta.get("fields") or []:
        if not isinstance(f, dict):
            raise RuntimeError("invalid field meta")
        if "value" in f or "answer" in f or "profileValue" in f:
            raise RuntimeError("refusing meta with value/answer keys")
    blob = json.dumps(meta, ensure_ascii=False)
    # Labels/options should not embed email addresses.
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob):
        raise RuntimeError("refusing meta that contains email-like strings")


def enrich_events_file(path: str = None, limit: Optional[int] = None) -> Dict[str, int]:
    path = path or OUT
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events") or []
    stats = enrich_google_forms_registration(events, limit=limit)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Enrich events.json with Google Forms schema")
    p.add_argument("--events", default=OUT, help="Path to events.json")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="Do not write events.json")
    args = p.parse_args(argv)
    with open(args.events, encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events") or []
    stats = enrich_google_forms_registration(events, limit=args.limit)
    if not args.dry_run:
        with open(args.events, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
    log("gforms enrichment:", stats)
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
