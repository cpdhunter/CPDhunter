"""
CPD Hunter - daily CPD collector v2.1
- Source-family parsers (HKIE, CIC, ICE, HKGBC, CSB/Labour, OSHC, CIPHE, HKICM)
- Better date parsing for common formats
- Status: OK_WITH_EVENTS / VERIFIED_EMPTY / EMPTY_UNVERIFIED / FAIL
- Per-source diagnostics + source_health.json
- Auto GitHub Issue after 3 consecutive FAIL/EMPTY_UNVERIFIED
- Cloudflare AI only for ambiguous classification
- Playwright for JS/SSL cases
"""
import json, os, re, sys, time, hashlib, datetime as dt
from urllib.parse import urljoin, urlparse
import urllib.robotparser

import requests
from bs4 import BeautifulSoup

from event_mode import attach_mode
from title_quality import (
    clamp_title,
    is_date_only_title,
    is_filter_or_badge_title,
    is_good_title,
    is_time_only_title,
    strip_hkgbc_badges,
    strip_cic_type_prefix,
    strip_page_chrome,
    title_quality_reason,
    CIC_EVENT_TYPE_LABELS,
)

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "events.json")
SOURCES = os.path.join(ROOT, "sources.json")
MANUAL = os.path.join(ROOT, "manual.json")
HEALTH = os.path.join(ROOT, "source_health.json")

BOT = "CPDHunterBot"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 (compatible; CPDHunterBot/2.2; free CPD calendar)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,zh-HK;q=0.8",
}
HKT = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(HKT).date()
KEEP_DAYS_AHEAD = 180
KEEP_DAYS_PAST = 31

TYPES = ["Technical", "GPM", "H&S"]
DISCS = ["Aircraft", "Biomedical", "Building", "Building Services", "Chemical", "Civil",
         "Control, Automation & Instrumentation", "Electrical", "Electronics", "Energy",
         "Environmental", "Fire", "Gas", "Geotechnical", "Information", "Logistics & Transportation",
         "Manufacturing, Industrial & Systems", "Marine & Naval Architecture", "Materials",
         "Mechanical", "Nuclear", "Structural", "General"]

HS_KW = re.compile(r"safety|health|hazard|accident|risk assessment|confined space|lifting|crane|scaffold|work at height|heat stress|職安|安全|健康|意外|吊運|棚架|高空工作", re.I)
GPM_KW = re.compile(r"contract|NEC|management|law|legal|ethics|integrity|leadership|communication|dispute|arbitration|procurement|合約|管理|法律|道德|誠信|溝通|仲裁|採購", re.I)

MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
          "january":1,"february":2,"march":3,"april":4,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12}

_robots = {}
CF_ACCOUNT = os.getenv("CLOUDFLARE_ACCOUNT_ID")
CF_TOKEN = os.getenv("CLOUDFLARE_AI_TOKEN")
CF_API = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/@cf/meta/llama-3.1-8b-instruct-fast" if CF_ACCOUNT else None

class StepError(Exception):
    pass

def log(*a):
    print(*a, file=sys.stderr, flush=True)

def allowed(url):
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers=HEADERS, timeout=15)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            rp.parse([])
        _robots[base] = rp
    return _robots[base].can_fetch(BOT, url)

def fetch_html(url, use_playwright=False, session=None):
    if not allowed(url):
        raise StepError("robots.txt 唔准讀取")
    if use_playwright and PLAYWRIGHT_OK:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(url, timeout=50000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
                return html
        except Exception as ex:
            raise StepError(f"Playwright 失敗：{type(ex).__name__}")
    last = None
    http = session or requests
    for attempt in range(2):
        try:
            r = http.get(url, headers=HEADERS, timeout=40, verify=True)
        except requests.exceptions.SSLError:
            raise StepError("讀取網頁失敗：SSL 憑證問題")
        except requests.exceptions.Timeout:
            last = "讀取網頁失敗：逾時"; time.sleep(5); continue
        except Exception as ex:
            last = f"讀取網頁失敗：{type(ex).__name__}"; time.sleep(5); continue
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
        last = f"讀取網頁失敗：HTTP {r.status_code}" + ("（網站封鎖咗雲端伺服器）" if r.status_code in (401,403,429) else "")
        if r.status_code in (401,403,404): break
        time.sleep(5)
    raise StepError(last or "讀取網頁失敗")

def parse_date(s):
    if not s: return None
    s = str(s).strip()
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try: return dt.date(y, mo, d).isoformat()
        except: pass
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        try: return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except: pass
    # "4 & 7-11 December 2026" / "28 & 29 December 2026" → first day
    m = re.search(r"(\d{1,2})\s*&\s*\d{1,2}(?:[-\u2013]\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})", s)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        if mon in MONTHS:
            try: return dt.date(year, MONTHS[mon], day).isoformat()
            except: pass
    m = re.search(r"(\d{1,2})(?:[-\u2013]\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})", s)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        if mon in MONTHS:
            try: return dt.date(year, MONTHS[mon], day).isoformat()
            except: pass
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", s)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        if mon in MONTHS:
            try: return dt.date(year, MONTHS[mon], day).isoformat()
            except: pass
    return None


def parse_time_range(text):
    """Parse a start–end clock range → ('HH:MM','HH:MM') or None.
    Supports 9:30 – 17:30, 09:30-17:30, 0900 - 1700, 9:30am - 6:30pm,
    1:30pm - 5:00pm, en/em dashes.
    """
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text)).strip()
    # Compact military-style HHMM - HHMM (no colon)
    m4 = re.match(r"^(\d{2})(\d{2})\s*[-–—]\s*(\d{2})(\d{2})$", t)
    if m4:
        sh, sm, eh, em = (int(m4.group(i)) for i in range(1, 5))
        if 0 <= sh <= 23 and 0 <= sm <= 59 and 0 <= eh <= 23 and 0 <= em <= 59:
            return f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}"
        return None
    m = re.match(
        r"^(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\s*[-–—]\s*"
        r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?$",
        t,
        re.I,
    )
    if not m:
        return None
    sh, sm, sap, eh, em, eap = m.groups()
    # Require minutes on both sides when no am/pm (avoid matching bare date fragments)
    if not sap and not eap and (sm is None or em is None):
        return None

    def _hhmm(h, mi, ap, peer_ap=None):
        h = int(h)
        mi = int(mi or 0)
        ap = (ap or peer_ap or "").lower().replace(".", "")
        if ap.startswith("p") and h != 12:
            h += 12
        elif ap.startswith("a") and h == 12:
            h = 0
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            return None
        return f"{h:02d}:{mi:02d}"

    # If only one side has am/pm, reuse it for the other when that side looks 12h-ish
    start = _hhmm(sh, sm, sap, eap if not sap else None)
    end = _hhmm(eh, em, eap, sap if not eap else None)
    if not start or not end:
        return None
    return start, end


def hours_from_range(start, end):
    """Minutes end-start (overnight if end < start); accept 20..720; round to nearest 0.5h."""
    if not start or not end:
        return None
    try:
        s = dt.datetime.strptime(str(start).strip(), "%H:%M")
        e = dt.datetime.strptime(str(end).strip(), "%H:%M")
    except Exception:
        return None
    mins = (e - s).total_seconds() / 60.0
    if mins < 0:
        mins += 24 * 60
    if 20 <= mins <= 720:
        return round(mins / 30) / 2
    return None


def stated_cpd_hours(text):
    """Organiser-stated duration like 'any 3 hours' or a clear 'N hours' line."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text)).strip()
    m = re.match(r"(?i)^any\s+(\d+(?:\.\d+)?)\s*hours?$", t)
    if m:
        v = float(m.group(1))
        return v if 0 < v < 50 else None
    m = re.match(r"(?i)^(\d+(?:\.\d+)?)\s*hours?$", t)
    if m:
        v = float(m.group(1))
        return v if 0 < v < 50 else None
    return None


def extract_oshc(soup, base):
    out = []
    # Prefer explicit activity links from OSHC seminars JS helpers
    html = str(soup)
    js_map = {}
    for m in re.finditer(
        r"checkButtonClick\(\s*'eng'\s*,\s*'seminars_conferences'\s*,\s*'((?:\\'|[^'])*)'\s*,\s*'((?:\\'|[^'])*)'",
        html,
        re.I,
    ):
        title = m.group(1).replace("\\'", "'")
        href = m.group(2).replace("\\'", "'").strip()
        if href.startswith("http"):
            js_map[re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.lower())] = href
    for table in soup.find_all("table"):
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 2: continue
            date_s = tds[0].get_text(strip=True)
            title = tds[1].get_text(strip=True)
            d = parse_date(date_s)
            if d and title:
                url = base
                key = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.lower())
                if key in js_map:
                    url = js_map[key]
                else:
                    # fuzzy: longest js title contained / containing
                    for jt, href in js_map.items():
                        if key and (key in jt or jt in key) and len(key) > 20:
                            url = href
                            break
                out.append({"title": title, "date": d, "url": url, "organizer": "OSHC", "is_online": "Online" in title or None})
    return out

def extract_hkie_cpd(soup, base):
    """Parse one Elementor CPD card/container at a time (title+date+url same card)."""
    out = []
    cards = soup.select(".e-loop-item")
    if not cards:
        # Fallback: populated widget wraps that contain a CPD code heading
        cards = []
        for wrap in soup.select(".elementor-widget-wrap"):
            txt = wrap.get_text("\n", strip=True)
            if re.search(r"\bCPD\d{3,}/\d{4}\b", txt):
                cards.append(wrap)
    for card in cards:
        lines = [ln.strip() for ln in card.get_text("\n", strip=True).splitlines() if ln.strip()]
        if not lines:
            continue
        title = None
        date_s = None
        start_t = None
        end_t = None
        cpd_h = None
        # Prefer explicit heading
        for h in card.select("h1, h2, h3, h4, .elementor-heading-title"):
            ht = re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip()
            if not ht:
                continue
            if re.match(r"^CPD\d", ht, re.I):
                continue
            if is_date_only_title(ht) or is_time_only_title(ht) or parse_time_range(ht) or stated_cpd_hours(ht) is not None:
                continue
            if len(ht) >= 15:
                title = ht
                break
        # Line scan inside THIS card only
        for ln in lines:
            if re.match(r"^CPD\d", ln, re.I):
                continue
            sh = stated_cpd_hours(ln)
            if sh is not None:
                cpd_h = sh
                continue
            tr = parse_time_range(ln)
            if tr or is_time_only_title(ln):
                if tr:
                    start_t, end_t = tr
                continue
            if is_date_only_title(ln) or parse_date(ln):
                if date_s is None and parse_date(ln):
                    date_s = ln
                continue
            if title is None and len(ln) >= 15 and not is_filter_or_badge_title(ln):
                title = ln
        if not title or not date_s:
            continue
        if is_date_only_title(title) or is_time_only_title(title) or parse_time_range(title) or stated_cpd_hours(title) is not None:
            continue
        d = parse_date(date_s)
        if not d:
            continue
        a = card.find("a", href=True)
        url = urljoin(base, a["href"]) if a else base
        ev = {"title": title, "date": d, "url": url, "organizer": "HKIE"}
        if start_t and end_t:
            ev["start_time"] = start_t
            ev["end_time"] = end_t
        if cpd_h is not None:
            ev["cpd_hours"] = cpd_h
        out.append(ev)
    # Dedup by date+title
    seen = set()
    uniq = []
    for e in out:
        k = (e["date"], e["title"][:80])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:40]


def _labour_venue_line(ln):
    return bool(re.search(r"圖書館|演講廳|講座室|診所|太空館|港鐵|銅鑼灣|尖沙咀|粉嶺|中央", ln or ""))


def _clean_labour_venue(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def extract_labour(soup, base):
    """Parse Labour OSH talk datatable rows: date/time/topic from SAME row."""
    out = []
    rows = soup.select("tr.ui-widget-content") or []
    if not rows:
        # Generic table fallback
        for table in soup.find_all("table"):
            rows.extend(table.find_all("tr")[1:])
    for tr in rows:
        lines = [ln.strip() for ln in tr.get_text("\n", strip=True).splitlines() if ln.strip()]
        if not lines:
            continue
        date_s = None
        time_s = None
        title_parts = []
        venue_parts = []
        venue_started = False
        for ln in lines:
            if ln in ("現正接受報名", "報名", "講座題目", "講座地點", "Accepting registration"):
                continue
            if date_s is None and parse_date(ln):
                date_s = ln
                continue
            if time_s is None and (is_time_only_title(ln) or parse_time_range(ln)):
                time_s = ln
                continue
            if is_time_only_title(ln) or parse_time_range(ln) or is_date_only_title(ln):
                continue
            # Venue heuristics — stop collecting title once venue-like line appears
            if _labour_venue_line(ln):
                venue_started = True
            if venue_started:
                venue_parts.append(ln)
                continue
            if parse_date(ln):
                continue
            title_parts.append(ln)
        if not date_s:
            continue
        title = re.sub(r"\s+", " ", " ".join(title_parts)).strip()
        # Prefer structured topic link text when present (keeps venue out of title)
        link = tr.select_one("a[href*='view.xhtml'], a.spinner-trigger[href]")
        if link:
            link_title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
            if link_title and not is_time_only_title(link_title) and not is_date_only_title(link_title) and len(link_title) >= 4:
                title = link_title
        if not title or is_time_only_title(title) or is_date_only_title(title) or is_filter_or_badge_title(title):
            continue
        if len(title) < 4:
            continue
        d = parse_date(date_s)
        if not d:
            continue
        url = base
        if link and link.get("href"):
            url = urljoin(base, link["href"])
        ev = {"title": title, "date": d, "url": url, "organizer": "Labour Dept"}
        venue_el = tr.select_one(".talkVenue")
        if venue_el:
            venue = _clean_labour_venue(venue_el.get_text(" ", strip=True))
        else:
            venue = _clean_labour_venue(" ".join(venue_parts))
        if venue:
            ev["venue"] = venue
        if time_s:
            times = parse_time_range(time_s)
            if times:
                ev["start_time"], ev["end_time"] = times
        out.append(ev)
    # Fallback: line-scan but NEVER accept time-only as title; stay within block
    if not out:
        lines = soup.get_text("\n", strip=True).splitlines()
        i = 0
        while i < len(lines):
            d = parse_date(lines[i])
            if not d:
                i += 1
                continue
            time_s = None
            title_parts = []
            venue = ""
            j = i + 1
            while j < len(lines) and j < i + 10:
                ln = lines[j].strip()
                if parse_date(ln) and j > i + 1:
                    break
                if is_time_only_title(ln) or parse_time_range(ln):
                    if time_s is None:
                        time_s = ln
                    j += 1
                    continue
                if ln in ("現正接受報名", "報名"):
                    j += 1
                    break
                if _labour_venue_line(ln):
                    venue_parts = [ln]
                    j += 1
                    while j < len(lines) and j < i + 20:
                        ln2 = lines[j].strip()
                        if parse_date(ln2) and j > i + 1:
                            break
                        if ln2 in ("現正接受報名", "報名"):
                            break
                        if ln2:
                            venue_parts.append(ln2)
                        j += 1
                    venue = _clean_labour_venue(" ".join(venue_parts))
                    break
                if ln and not is_date_only_title(ln):
                    title_parts.append(ln)
                j += 1
            title = re.sub(r"\s+", " ", " ".join(title_parts)).strip()
            if title and not is_time_only_title(title) and len(title) >= 4:
                ev = {"title": title, "date": d, "url": base, "organizer": "Labour Dept"}
                if venue:
                    ev["venue"] = venue
                if time_s:
                    times = parse_time_range(time_s)
                    if times:
                        ev["start_time"], ev["end_time"] = times
                out.append(ev)
            i = j if j > i + 1 else i + 1
    seen = set()
    uniq = []
    for e in out:
        k = (e["date"], e["title"][:80])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:20]



_LABOUR_REG_CHROME_RE = re.compile(
    r"職業健康公開講座\s*[-–—]?\s*網上報名(?:須知)?|網上報名(?:須知)?"
)


def _strip_labour_registration_chrome(text):
    """網上報名 is registration, not an online joining option."""
    return re.sub(r"\s+", " ", _LABOUR_REG_CHROME_RE.sub(" ", text or "")).strip()


def parse_labour_talk_detail(html):
    """Extract labelled talk fields from an official OSHSREG talk detail page."""
    soup = BeautifulSoup(html or "", "html.parser")
    venue = None
    date_s = None
    time_s = None
    table = soup.select_one("table.tableTalkView")
    if table:
        for tr in table.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 2:
                continue
            label = re.sub(r"\s+", " ", tds[0].get_text(" ", strip=True)).strip()
            value = re.sub(r"\s+", " ", tds[1].get_text(" ", strip=True)).strip()
            if "講座地點" in label or label.lower() in ("地點", "venue"):
                venue = value
            elif "講座日期" in label:
                date_s = value
            elif "講座時間" in label:
                time_s = value
    title = ""
    description = ""
    content = soup.select_one("#content")
    if content:
        parts = []
        for child in content.children:
            name = getattr(child, "name", None)
            classes = child.get("class") if getattr(child, "get", None) else None
            if name == "table" and classes and "tableTalkView" in classes:
                break
            if not getattr(child, "get_text", None):
                continue
            t = re.sub(r"\s+", " ", child.get_text(" ", strip=True)).strip()
            if t and t != "講座詳情":
                parts.append(t)
        if parts:
            title = parts[0]
            description = " ".join(parts[1:])
    return {
        "title": title,
        "venue": venue or "",
        "description": _strip_labour_registration_chrome(description),
        "date": date_s,
        "time": time_s,
    }


def enrich_labour_talk_details(events, fetch_detail):
    """Classify Labour talks from each official talk detail page, not the listing venue."""
    from event_mode import infer_mode, MODE_UNKNOWN

    out = []
    for ev in events or []:
        item = dict(ev)
        url = item.get("url") or ""
        if "selectedTalkHdr=" not in url or not callable(fetch_detail):
            out.append(item)
            continue
        try:
            html = fetch_detail(url)
        except Exception:
            out.append(item)
            continue
        if not html:
            out.append(item)
            continue
        detail = parse_labour_talk_detail(html)
        detail_venue = (detail.get("venue") or "").strip()
        if not detail_venue:
            log(f"  labour detail has no labelled 講座地點: {url}")
        if detail_venue:
            item["venueSource"] = "event_detail"
            if not item.get("venue"):
                item["venue"] = detail_venue
        desc = (detail.get("description") or "").strip()
        if desc and not item.get("description"):
            item["description"] = desc
        evidence = {
            "name": detail.get("title") or item.get("title"),
            "venue": detail_venue or None,
            "description": desc or None,
            "venueSource": "event_detail" if detail_venue else "",
        }
        inferred = infer_mode(evidence)
        if inferred["mode"] != MODE_UNKNOWN:
            item["mode"] = inferred["mode"]
        out.append(item)
    return out


def extract_ice(soup, base):
    out = []
    for art in soup.find_all(["article", "div", "li"]):
        text = art.get_text("\n", strip=True)
        if "Date" not in text and "date" not in text.lower(): continue
        title_el = art.find(["h2", "h3", "h4", "a"])
        title = title_el.get_text(strip=True) if title_el else ""
        if len(title) < 10: continue
        if not is_good_title(title):
            continue
        d = parse_date(text)
        if d:
            a = art.find("a", href=True)
            url = urljoin(base, a["href"]) if a else base
            online = "Online" in text or "Webinar" in text
            free = "Free" in text and "From £" not in text and "$" not in text
            out.append({"title": title, "date": d, "url": url, "organizer": "ICE", "is_online": online, "is_free": free or None})
    seen = set()
    uniq = []
    for e in out:
        k = e["title"][:80]
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:40]



def _cic_clean_title(title: str) -> str:
    """Strip leading dd.mm.yyyy (or ranges) and Event Types prefixes; reject pure labels."""
    t = re.sub(r"\s+", " ", (title or "")).strip()
    t = re.sub(r"^\d{2}\.\d{2}\.\d{4}(?:\s*-\s*\d{2}\.\d{2}\.\d{4})?\s+", "", t).strip()
    t = re.sub(r"^\d{4}-\d{2}-\d{2}\s+", "", t).strip()
    t = strip_cic_type_prefix(t)
    if not t or is_filter_or_badge_title(t) or is_date_only_title(t) or is_time_only_title(t):
        return ""
    return t

def extract_cic(soup, base):
    """CIC events: require real calendar/card titles; reject Event Types filter labels."""
    out = []
    # Prefer event anchors / cards with a date in the same container
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        # Skip pure filter/navigation chrome
        parent = a.find_parent(["option", "select"])
        if parent:
            continue
        title = _cic_clean_title(a.get_text(" ", strip=True))
        # Prefer headings inside a card when present
        card = a.find_parent(["article", "li", "div", "td", "tr"])
        if card:
            for h in card.find_all(["h1", "h2", "h3", "h4"]):
                ht = _cic_clean_title(h.get_text(" ", strip=True))
                if ht and len(ht) >= 5:
                    title = ht
                    break
            ctx = card.get_text(" ", strip=True)
        else:
            ctx = a.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue
        d = parse_date(ctx) or parse_date(a.get_text(" ", strip=True))
        if not d:
            continue
        out.append({"title": title, "date": d, "url": urljoin(base, href), "organizer": "CIC"})
    # Legacy dd.mm.yyyy line scan — still reject filter labels
    if not out:
        text = soup.get_text("\n", strip=True)
        for m in re.finditer(r"(\d{2}\.\d{2}\.\d{4}(?:\s*-\s*\d{2}\.\d{2}\.\d{4})?)\s+(.+?)(?:\n|$)", text):
            d = parse_date(m.group(1).split("-")[0].strip())
            title = _cic_clean_title(m.group(2).strip())
            if not d or not title or len(title) < 5:
                continue
            out.append({"title": title, "date": d, "url": base, "organizer": "CIC"})
    seen = set()
    uniq = []
    for e in out:
        k = (e["date"], e["title"][:80])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:40]


def extract_rstcs(soup, base):
    """RSTCS events page: Zoom webinar/register links and dated cards."""
    out = []
    html = str(soup)
    # Zoom registration links with nearby title
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "zoom.us" not in href.lower() or "register" not in href.lower():
            continue
        parent = a.find_parent(["div", "li", "article", "tr", "section"])
        title = a.get_text(strip=True) or (parent.get_text(" ", strip=True)[:200] if parent else "")
        title = strip_page_chrome(title)
        ctx = parent.get_text(" ", strip=True) if parent else title
        d = parse_date(ctx)
        # Summit 2026 without a clear day — skip undated rather than invent
        if not d:
            # try year-only future placeholder from title
            ym = re.search(r"(20\d{2})", title)
            if ym and int(ym.group(1)) >= TODAY.year:
                # Without a real day, do not invent a date
                continue
            continue
        if not is_good_title(title):
            continue
        out.append({
            "title": clamp_title(title) or "RSTCS event",
            "date": d,
            "url": urljoin(base, href),
            "organizer": "CIC RSTCS",
            "is_online": True,
            "is_free": True,
        })
    # Also generic dated anchors on the page
    if not out:
        for a in soup.find_all("a", href=True):
            parent = a.find_parent(["div", "li", "article", "tr"])
            ctx = (parent.get_text(" ", strip=True) if parent else "") + " " + a.get_text()
            d = parse_date(ctx)
            title = strip_page_chrome(a.get_text(strip=True))
            if d and title and len(title) > 12 and is_good_title(title) and "facebook" not in (a.get("href") or "").lower():
                out.append({"title": clamp_title(title), "date": d, "url": urljoin(base, a["href"]), "organizer": "CIC RSTCS"})
    seen = set()
    uniq = []
    for e in out:
        k = (e["date"], e["title"][:60])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:20]


def extract_csb(soup, base):
    out = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all(["td", "th"])
            if len(tds) < 2: continue
            date_s = tds[0].get_text(strip=True)
            title = tds[1].get_text(strip=True)
            d = parse_date(date_s)
            if d and title:
                a = tds[1].find("a", href=True)
                href = (a.get("href") or "").strip() if a else ""
                url = urljoin(base, href) if href else base
                out.append({"title": title, "date": d, "url": url, "organizer": tds[2].get_text(strip=True) if len(tds)>2 else "CSB/Labour"})
    return out


def _hkgbc_detail_title(html: str) -> str:
    """Prefer H1 → heading → og:title → page title minus site chrome."""
    soup = BeautifulSoup(html, "html.parser")
    for sel in ["h1", "h2.event-title", ".event-title", "h2", "h3"]:
        el = soup.select_one(sel) if "." in sel or sel.startswith("h") else None
        if sel.startswith("h") and "." not in sel:
            el = soup.find(sel)
        if not el:
            continue
        t = strip_hkgbc_badges(el.get_text(" ", strip=True))
        t = strip_page_chrome(t)
        if t and is_good_title(t) and len(t) >= 8:
            return t
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        t = strip_hkgbc_badges(og["content"])
        t = re.sub(r"\s*\|\s*HKGBC.*$", "", t, flags=re.I).strip()
        t = strip_page_chrome(t)
        if t and is_good_title(t) and len(t) >= 8:
            return t
    if soup.title:
        t = strip_hkgbc_badges(soup.title.get_text(strip=True))
        t = re.sub(r"\s*\|\s*HKGBC.*$", "", t, flags=re.I).strip()
        t = strip_page_chrome(t)
        if t and is_good_title(t) and len(t) >= 8:
            return t
    return ""


def extract_hkgbc(soup, base, fetch_detail=None):
    extract_hkgbc._detail_fetches = 0
    """
    HKGBC listing: prefer p.title; strip badge chrome; never store badge-only titles.
    Optional fetch_detail(url)->html for badge-only rows needing a detail H1/og:title.
    """
    out = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "events-detail" not in href.lower() and "eventid=" not in href.lower():
            continue
        parent = a.find_parent(["div", "li", "article", "tr", "section"])
        d = None
        title = ""
        if parent:
            # Structured fields
            date_el = parent.select_one("span.eventDate, .eventDate, p.date span.eventDate")
            title_el = parent.select_one("p.title, .title")
            if date_el:
                d = parse_date(date_el.get_text(" ", strip=True))
            if title_el:
                title = title_el.get_text(" ", strip=True)
            if not d:
                d = parse_date(parent.get_text(" ", strip=True))
        if not title:
            title = a.get_text(" ", strip=True) or ""
        title = strip_hkgbc_badges(title)
        title = re.sub(r"\s+", " ", title).strip()
        if "|" in title:
            bits = [b.strip() for b in title.split("|") if b.strip()]
            # Drop badge-only bits
            bits = [b for b in bits if not is_filter_or_badge_title(b) and not (parse_date(b) and len(b) < 24)]
            bits = sorted(bits, key=len, reverse=True)
            title = bits[0] if bits else title
        title = strip_hkgbc_badges(title)
        detail_url = urljoin(base, href)
        # Detail fetch only for badge-only/empty titles; cap to avoid listing timeouts.
        if (not title or not is_good_title(title) or len(title) < 8) and fetch_detail:
            n_detail = getattr(extract_hkgbc, "_detail_fetches", 0)
            if n_detail < 8:
                try:
                    html = fetch_detail(detail_url)
                    title = _hkgbc_detail_title(html) or title
                    extract_hkgbc._detail_fetches = n_detail + 1
                except Exception:
                    pass
        if not d or not title or not is_good_title(title) or len(title) < 8:
            continue
        if parse_date(title) and len(title) < 24:
            continue
        out.append({"title": clamp_title(title), "date": d, "url": detail_url, "organizer": "HKGBC"})
    if not out:
        text = soup.get_text("\n", strip=True)
        for m in re.finditer(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}年\d{1,2}月\d{1,2}日)\s*\|\s*(.+?)(?:\n|$)", text):
            d = parse_date(m.group(1))
            title = strip_hkgbc_badges(m.group(2).strip())
            if d and title and len(title) > 8 and is_good_title(title):
                out.append({"title": clamp_title(title), "date": d, "url": base, "organizer": "HKGBC"})
    # Dedup by date+title
    seen = set()
    uniq = []
    for e in out:
        k = (e["date"], e["title"][:80])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:40]


def extract_hkie_div(soup, base):
    out = []
    for art in soup.find_all(["article", "div", "li"]):
        title_el = art.find(["h2", "h3", "a"])
        if not title_el: continue
        title = title_el.get_text(strip=True)
        if len(title) < 15: continue
        if not is_good_title(title):
            continue
        text = art.get_text(" ", strip=True)
        d = parse_date(text)
        if d:
            a = art.find("a", href=True)
            url = urljoin(base, a["href"]) if a else base
            out.append({"title": title, "date": d, "url": url, "organizer": "HKIE Division"})
    return out[:20]


def generic_extract(soup, base):
    """Prefer H1/heading/og over chrome-filled anchor text; strip Begins/Find out more."""
    out = []
    # Detail-page style: single primary title
    h1 = soup.find("h1")
    og = soup.find("meta", property="og:title")
    page_primary = None
    if h1:
        page_primary = strip_page_chrome(h1.get_text(" ", strip=True))
    if (not page_primary or not is_good_title(page_primary)) and og and og.get("content"):
        page_primary = strip_page_chrome(re.sub(r"\s*\|.*$", "", og["content"]))
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if not txt or len(txt) < 8: continue
        parent = a.find_parent(["li", "div", "article", "tr", "p", "section"])
        ctx = parent.get_text(" ", strip=True) if parent else txt
        d = parse_date(ctx) or parse_date(txt)
        if not d:
            continue
        title = None
        if parent:
            for h in parent.find_all(["h1", "h2", "h3", "h4"]):
                ht = strip_page_chrome(h.get_text(" ", strip=True))
                if ht and len(ht) >= 8 and is_good_title(ht):
                    title = ht
                    break
        if not title:
            title = strip_page_chrome(txt)
        # If still chrome-y but page has a clean primary and URL looks like a detail page
        if page_primary and is_good_title(page_primary):
            href = (a.get("href") or "")
            path_match = urlparse(urljoin(base, href)).path.rstrip("/") == urlparse(base).path.rstrip("/")
            contains_primary = bool(title) and page_primary.lower() in title.lower()
            chrome_extra = bool(title) and (
                "begins" in title.lower()
                or "find out more" in title.lower()
                or (contains_primary and len(title) > len(page_primary) + 10)
            )
            if (not title or not is_good_title(title) or chrome_extra) and (path_match or "event" in href.lower()):
                if contains_primary or page_primary.lower() in ctx.lower() or path_match:
                    title = page_primary
        if not title or not is_good_title(title) or len(title) < 8:
            continue
        out.append({"title": clamp_title(title), "date": d, "url": urljoin(base, a["href"]), "organizer": None})
    # Dedup preferring shorter clean titles for same URL+date
    best = {}
    for e in out:
        k = (e["date"], e["url"])
        prev = best.get(k)
        if prev is None:
            best[k] = e
            continue
        # Prefer title without chrome words / shorter reasonable title
        def score(t):
            s = 0
            if "begins" in t.lower() or "find out more" in t.lower():
                s -= 50
            s -= abs(len(t) - 60) / 10
            return s
        if score(e["title"]) > score(prev["title"]):
            best[k] = e
    return list(best.values())[:20]


def classify_rule(title):
    if HS_KW.search(title): return "H&S"
    if GPM_KW.search(title): return "GPM"
    return "Technical"

def ai_classify(title, org):
    if not CF_API or not CF_TOKEN: return None
    prompt = f'Return strict JSON only: {{"type":"Technical|GPM|H&S","disciplines":["one of {DISCS}"]}}. Event: {title} by {org}. No other text.'
    try:
        r = requests.post(CF_API, headers={"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"},
                          json={"messages": [{"role": "user", "content": prompt}]}, timeout=25)
        if r.status_code != 200: return None
        content = r.json().get("result", {}).get("response", "") or r.text
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            data = json.loads(m.group(0))
            typ = data.get("type") if data.get("type") in TYPES else None
            discs = [x for x in (data.get("disciplines") or []) if x in DISCS]
            return typ, discs or ["General"]
    except Exception:
        pass
    return None

def clean(e, src, rejects):
    try:
        title = clamp_title(strip_page_chrome((e.get("title") or "").strip()))
        # HKGBC badge prefixes may still arrive from older extract paths
        if "hkgbc" in (src.get("url") or "").lower() or (e.get("organizer") or "") == "HKGBC":
            title = clamp_title(strip_hkgbc_badges(title))
        date = parse_date(e.get("date")) or e.get("date")
        if not date:
            rejects["no_date"] = rejects.get("no_date", 0) + 1
            return None
        e["date"] = dt.date.fromisoformat(str(date)[:10]).isoformat()
        url = e.get("url") or src["url"]
        reason = title_quality_reason(title)
        if reason or not title or not str(url).startswith("http"):
            rejects["bad_title"] = rejects.get("bad_title", 0) + 1
            return None
        d = dt.date.fromisoformat(e["date"])
        if d < TODAY or d > TODAY + dt.timedelta(days=KEEP_DAYS_AHEAD):
            rejects["date_range"] = rejects.get("date_range", 0) + 1
            return None
        if e.get("is_free") is False:
            rejects["paid"] = rejects.get("paid", 0) + 1
            return None
        if src["region"] != "HK" and e.get("is_online") is False:
            rejects["overseas_physical"] = rejects.get("overseas_physical", 0) + 1
            return None
        if any(x in title.lower() for x in ["dinner", "agm", "sport", "social", "gala", "banquet"]):
            rejects["social"] = rejects.get("social", 0) + 1
            return None
        typ = e.get("type") or classify_rule(title)
        discs = e.get("disciplines") or ["General"]
        if typ not in TYPES or not any(x in DISCS for x in discs):
            ai = ai_classify(title, e.get("organizer") or src["name"])
            if ai:
                typ, discs = ai
            else:
                typ = typ if typ in TYPES else (src.get("type") or "Technical")
                discs = [x for x in discs if x in DISCS] or ["General"]
        hrs = e.get("cpd_hours")
        hrs = hrs if isinstance(hrs, (int, float)) and 0 < hrs < 50 else None
        est = False
        s_hkt, e_hkt = e.get("start_time"), e.get("end_time")
        # If start/end missing, try raw time-ish fields (organiser listing text)
        if not (s_hkt and e_hkt):
            for raw in (e.get("time"), e.get("time_raw"), e.get("time_s")):
                tr = parse_time_range(raw) if raw else None
                if tr:
                    s_hkt, e_hkt = tr
                    break
        if hrs is None:
            for raw in (e.get("time"), e.get("time_raw"), e.get("duration"), e.get("hours_text")):
                sh = stated_cpd_hours(raw) if raw else None
                if sh is not None:
                    hrs = sh
                    est = False
                    break
        if hrs is None and s_hkt and e_hkt:
            h = hours_from_range(s_hkt, e_hkt)
            if h is not None:
                hrs = h
                est = True
        out = {
            "id": "a" + hashlib.sha1((re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.lower()) + "|" + e["date"]).encode()).hexdigest()[:12],
            "name": clamp_title(title),
            "org": (e.get("organizer") or src["name"])[:120],
            "date": e["date"],
            "time": f"{s_hkt}-{e_hkt}" if s_hkt and e_hkt else (s_hkt or ""),
            "hrs": hrs,
            "hrs_est": est,
            "type": typ,
            "disc": discs,
            "url": url,
            "region": src["region"],
            "online": e.get("is_online"),
            "free": e.get("is_free") if e.get("is_free") is not None else src.get("free"),
            "source": src["name"],
            "group": src.get("group") or src["name"],
            "auto": True,
        }
        # Optional non-PII destination hint from source parsers (Sprint 2C2).
        # Uses existing registration metadata shape; never stores profile values.
        dest = e.get("registration_destination")
        if isinstance(dest, str) and dest.startswith("http"):
            low = dest.lower()
            if "forms.gle" in low or "docs.google.com/forms" in low or "google.com/forms" in low:
                mech = "GOOGLE_FORMS"
            elif "forms.office.com" in low:
                mech = "MICROSOFT_FORMS"
            elif "eventbrite." in low:
                mech = "EVENTBRITE"
            elif "zoom.us" in low:
                mech = "ZOOM"
            elif "sms.oshc.hk" in low and "activity" in low:
                mech = "OSHC_PORTAL"
            else:
                mech = "OTHER_PUBLIC_FORM"
            out["registration"] = {
                "mechanism": mech,
                "destination": dest,
                "status": "OPEN",
                "sourceUrlClass": "DIRECT_REGISTRATION",
                "confidence": "HIGH",
                "discoveryMethod": "source_parser",
                "requiresManualCompletion": True,
            }
        # Optional evidence fields for conservative mode classification (non-PII).
        for key, limit in (
            ("venue", 160),
            ("location", 200),
            ("modeText", 200),
            ("attendanceMode", 80),
            ("description", 2000),
        ):
            raw = e.get(key)
            if isinstance(raw, str) and raw.strip():
                out[key] = raw.strip()[:limit]
        vs = e.get("venueSource")
        if isinstance(vs, str) and vs.strip():
            out["venueSource"] = vs.strip()[:40]
        explicit_mode = e.get("mode")
        if isinstance(explicit_mode, str) and explicit_mode.strip():
            out["mode"] = explicit_mode.strip()
        # Stamp mode only with reliable evidence. online=false / listing venue is not Face to Face.
        attach_mode(out)
        return out
    except Exception:
        rejects["exception"] = rejects.get("exception", 0) + 1
        return None

def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def process_source(src):
    url = src["url"]
    use_pw = False
    if "localevents.theiet" in url or "istructe" in url:
        use_pw = True
    # OSHSREG talk views need the listing JSESSIONID; a bare GET of selectedTalkHdr
    # returns the listing chrome without 講座地點.
    labour_session = None
    if "oshsreg.gov.hk" in url:
        labour_session = requests.Session()
        labour_session.headers.update(HEADERS)
    try:
        html = fetch_html(url, use_playwright=use_pw, session=labour_session)
    except StepError:
        # HKGBC listing often times out from cloud IPs — one Playwright retry.
        if (not use_pw) and PLAYWRIGHT_OK and "hkgbc" in url:
            html = fetch_html(url, use_playwright=True)
            use_pw = True
        else:
            raise
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    # Surface under-construction banners into title for status classification
    body_txt = soup.get_text(" ", strip=True)[:500].lower()
    if "page under construction" in body_txt and "under construction" not in title.lower():
        title = (title + " Page Under Construction").strip()
    raw = []
    method = "generic"
    if "sms.oshc.hk" in url and "activit" in url:
        from parsers.oshc_activity import (
            extract_oshc_activity,
            build_activity_url_index,
            attach_activity_urls,
        )
        raw = extract_oshc_activity(soup, url)
        method = "oshc-activity"
        # Resolve public activity detail URLs from OSHC seminars index (GET only).
        # Needed so frozen dedup can match against OSHC Seminars / CSB / Labour.
        try:
            idx_html = fetch_html(
                "https://www.oshc.org.hk/eng/main/training/seminars_conferences/",
                use_playwright=False,
            )
            raw = attach_activity_urls(raw, build_activity_url_index(idx_html))
        except Exception as ex:
            log(f"  oshc-activity url enrich skipped: {type(ex).__name__}")
    elif "oshc.org.hk" in url:
        raw = extract_oshc(soup, url)
        method = "oshc-table"
    elif "csb.gov.hk" in url:
        raw = extract_csb(soup, url)
        method = "csb-table"
    elif "oshsreg.gov.hk" in url or "labour.gov.hk" in url:
        raw = extract_labour(soup, url)
        method = "labour-list"
        if "oshsreg.gov.hk" in url:
            try:
                raw = enrich_labour_talk_details(
                    raw,
                    lambda u: fetch_html(u, use_playwright=False, session=labour_session),
                )
                method = "labour-list+detail"
            except Exception as ex:
                log(f"  labour detail enrich skipped: {type(ex).__name__}")
    elif "hkie.org.hk" in url and "cpd-calendar" in url:
        raw = extract_hkie_cpd(soup, url)
        method = "hkie-cpd"
    elif "hkie" in url and ("bd.hkie" in url or "hkie-st" in url or "hkie-fe" in url):
        raw = extract_hkie_div(soup, url)
        method = "hkie-div"
    elif "ice.org.uk" in url:
        raw = extract_ice(soup, url)
        method = "ice-cards"
    elif "rstc.cic" in url:
        raw = extract_rstcs(soup, url)
        method = "rstcs"
        if not raw:
            raw = extract_cic(soup, url)
            method = "cic-list"
    elif "cic.hk" in url or "bim.cic" in url or "citac" in url:
        raw = extract_cic(soup, url)
        method = "cic-list"
    elif "hkgbc" in url:
        def _hkgbc_fetch(detail_url):
            return fetch_html(detail_url, use_playwright=False)
        raw = extract_hkgbc(soup, url, fetch_detail=_hkgbc_fetch)
        method = "hkgbc"
    elif "ciphe.org.hk" in url:
        from parsers.ciphe import extract_ciphe
        raw = extract_ciphe(soup, url)
        method = "ciphe"
    elif "hkicm.org.hk" in url:
        from parsers.hkicm import extract_hkicm
        raw = extract_hkicm(soup, url)
        method = "hkicm"
    else:
        raw = generic_extract(soup, url)
        method = "generic"
    if not raw and PLAYWRIGHT_OK and not use_pw and ("hkie" in url or "ice" in url or "cic" in url or "hkgbc" in url):
        try:
            html2 = fetch_html(url, use_playwright=True)
            soup2 = BeautifulSoup(html2, "html.parser")
            if "hkie.org.hk" in url and "cpd" in url:
                raw = extract_hkie_cpd(soup2, url)
            elif "ice" in url:
                raw = extract_ice(soup2, url)
            elif "hkgbc" in url:
                raw = extract_hkgbc(soup2, url, fetch_detail=None)  # listing-only; no nested fetches
            elif "cic" in url:
                raw = extract_cic(soup2, url)
            else:
                raw = generic_extract(soup2, url)
            if raw:
                method = "playwright+" + method
        except Exception:
            pass
    return raw, method, title

def _norm_org(org):
    o = (org or "").lower()
    if "oshc" in o or "職安局" in o:
        return "oshc"
    if "csb" in o or "公務員" in o or "civil service" in o:
        return "csb"
    return re.sub(r"[^a-z0-9]", "", o)[:40]

def _norm_title(t):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (t or "").lower())

def _title_sim(a, b):
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    from difflib import SequenceMatcher
    return SequenceMatcher(None, na, nb).ratio()

def _strong_signal(a, b):
    ua, ub = a.get("url",""), b.get("url","")
    if ua and ub and ua == ub and ("event" in ua.lower() or "activity" in ua.lower() or "detail" in ua.lower()):
        return True
    if a.get("time") and a.get("time") == b.get("time") and a.get("hrs") and a.get("hrs") == b.get("hrs"):
        return True
    if a.get("hrs") and not a.get("hrs_est") and a.get("hrs") == b.get("hrs") and not b.get("hrs_est"):
        na, nb = _norm_title(a.get("name")), _norm_title(b.get("name"))
        for i in range(len(na)-19):
            phrase = na[i:i+20]
            if phrase in nb and len(set(phrase)) > 8:
                return True
    na, nb = _norm_title(a.get("name")), _norm_title(b.get("name"))
    campaigns = ["heartcaring", "joyfulhealthyworkplace", "joyful@healthy"]
    if any(c in na and c in nb for c in campaigns):
        subjects = ["cardiovascular", "mentalhealth", "breaks your heart", "breaksyourheart"]
        if any(s in na and s in nb for s in subjects):
            return True
    return False

def _prefer_source(a, b):
    sa = (a.get("source") or "").lower()
    sb = (b.get("source") or "").lower()
    if "oshc seminars" in sa and ("公務員" in sb or "csb" in sb or "civil service" in sb):
        return a
    if "oshc seminars" in sb and ("公務員" in sa or "csb" in sa or "civil service" in sa):
        return b
    def score(x):
        s = 0
        url = x.get("url","")
        if url and ("event-detail" in url or "/events/" in url or "activity" in url) and not url.endswith("/"):
            s += 2
        if x.get("hrs") is not None and not x.get("hrs_est"):
            s += 1
        s += len(x.get("name","")) / 100
        return s
    return a if score(a) >= score(b) else b

def dedup_events(events):
    from difflib import SequenceMatcher
    out = []
    used = set()
    for i, e in enumerate(events):
        if i in used:
            continue
        best = e
        for j in range(i+1, len(events)):
            if j in used:
                continue
            o = events[j]
            if e.get("date") != o.get("date"):
                continue
            if _norm_org(e.get("org")) != _norm_org(o.get("org")):
                continue
            sim = _title_sim(e.get("name"), o.get("name"))
            if sim < 0.90:
                continue
            if not _strong_signal(e, o):
                continue
            best = _prefer_source(best, o)
            used.add(j)
        out.append(best)
        used.add(i)
    return out


def backfill_hrs_from_time(events):
    """Fill missing hrs from stored HH:MM-HH:MM time (e.g. stale rows / raised duration cap)."""
    for e in events:
        if e.get("hrs") is not None:
            continue
        tr = parse_time_range(e.get("time") or "")
        if not tr:
            continue
        h = hours_from_range(tr[0], tr[1])
        if h is not None:
            e["hrs"] = h
            e["hrs_est"] = True
    return events

def main():
    sources = load(SOURCES, [])
    old = load(OUT, {}).get("events", [])
    found = {}
    status = []
    log(f"Playwright: {'yes' if PLAYWRIGHT_OK else 'no'}; CF AI: {'yes' if CF_API and CF_TOKEN else 'no'}")
    for src in sources:
        if src.get("disabled"): continue
        log(f"▶ {src['name']}")
        try:
            raw, method, page_title = process_source(src)
            rejects = {}
            n = 0
            for e in raw:
                c = clean(e, src, rejects)
                if c:
                    found[c["id"]] = c
                    n += 1
            if n > 0:
                st = "OK_WITH_EVENTS"
            elif rejects and all(k in ("date_range", "overseas_physical", "paid", "social") for k in rejects):
                st = "VERIFIED_EMPTY"
            elif "under construction" in (page_title or "").lower() or "page under construction" in (page_title or "").lower():
                st = "VERIFIED_EMPTY"
            else:
                st = "EMPTY_UNVERIFIED"
            log(f"  {st} {method}: raw={len(raw)} kept={n} rejects={rejects} title={page_title[:60]}")
            status.append({
                "source": src["name"], "status": st, "ok": st == "OK_WITH_EVENTS", "n": n,
                "method": method, "page_title": page_title[:80],
                "raw_candidates": len(raw), "rejects": rejects
            })
        except StepError as ex:
            log(f"  FAIL {ex}")
            status.append({"source": src["name"], "status": "FAIL", "ok": False, "n": 0, "err": str(ex)[:200]})
        except Exception as ex:
            log(f"  FAIL {type(ex).__name__}: {ex}")
            status.append({"source": src["name"], "status": "FAIL", "ok": False, "n": 0, "err": f"{type(ex).__name__}: {str(ex)[:150]}"})
        time.sleep(2)

    health = load(HEALTH, {})
    today_iso = TODAY.isoformat()
    for s in status:
        name = s["source"]
        prev = health.get(name, {})
        consec = prev.get("consecutive_fail", 0)
        if s["status"] in ("FAIL", "EMPTY_UNVERIFIED"):
            consec += 1
        else:
            consec = 0
        health[name] = {
            "last_status": s["status"],
            "last_n": s.get("n", 0),
            "last_method": s.get("method"),
            "last_error": s.get("err"),
            "raw_candidates": s.get("raw_candidates"),
            "rejects": s.get("rejects"),
            "consecutive_fail": consec,
            "last_success": today_iso if s["status"] == "OK_WITH_EVENTS" else prev.get("last_success"),
            "updated": today_iso,
        }
    with open(HEALTH, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=1)

    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if token and repo:
        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
            r = requests.get(f"https://api.github.com/repos/{repo}/issues", params={"state": "open", "labels": "cpd-source-maintenance"}, headers=headers, timeout=20)
            open_issues = {i["title"]: i["number"] for i in r.json()} if r.status_code == 200 else {}
            for name, h in health.items():
                title = f"[CPD Source] {name} needs maintenance"
                if h["consecutive_fail"] >= 3 and h["last_status"] in ("FAIL", "EMPTY_UNVERIFIED"):
                    body = f"""Source: {name}\nStatus: {h['last_status']}\nMethod: {h.get('last_method')}\nLast success: {h.get('last_success') or 'never'}\nConsecutive failures: {h['consecutive_fail']}\nRaw candidates: {h.get('raw_candidates')}\nRejects: {h.get('rejects')}\nError: {h.get('last_error') or ''}\n"""
                    if title not in open_issues:
                        requests.post(f"https://api.github.com/repos/{repo}/issues", json={"title": title, "body": body, "labels": ["cpd-source-maintenance"]}, headers=headers, timeout=20)
                elif h["last_status"] in ("OK_WITH_EVENTS", "VERIFIED_EMPTY") and title in open_issues:
                    requests.patch(f"https://api.github.com/repos/{repo}/issues/{open_issues[title]}", json={"state": "closed", "state_reason": "completed"}, headers=headers, timeout=20)
        except Exception as ex:
            log(f"Issue sync skipped: {ex}")

    cutoff = (TODAY - dt.timedelta(days=KEEP_DAYS_PAST)).isoformat()
    stale_bad = 0
    for e in old:
        if e.get("auto") and e.get("date", "") >= cutoff and e.get("id") not in found:
            # Do not preserve contaminated titles from prior scrapes (title fixes change IDs).
            if not is_good_title(e.get("name") or ""):
                stale_bad += 1
                continue
            found[e["id"]] = e
    if stale_bad:
        log(f"Dropped {stale_bad} stale contaminated title(s) from previous events.json")
    for e in load(MANUAL, []):
        if e.get("date", "") >= cutoff:
            e.setdefault("id", "m" + hashlib.sha1((e.get("url", "") + e["date"]).encode()).hexdigest()[:12])
            e["auto"] = False
            found[e["id"]] = e
    events = sorted(found.values(), key=lambda x: (x["date"], x.get("time") or ""))
    raw_count = len(events)
    events = dedup_events(events)
    log(f"Dedup: {raw_count} -> {len(events)}")
    # Post-scrape title quality gate (detect only; scrapers already reject)
    bad_future = []
    for e in events:
        if e.get("date", "") < TODAY.isoformat():
            continue
        reason = title_quality_reason(e.get("name") or "")
        if reason:
            bad_future.append((e.get("id"), reason, (e.get("name") or "")[:60]))
    if bad_future:
        log(f"TITLE QUALITY FAIL: {len(bad_future)} future event(s) with impossible titles:")
        for i, r, n in bad_future[:20]:
            log(f"  {i} {r}: {n}")
    else:
        log("TITLE QUALITY: 0 date-only / time-only / filter-label / HKGBC-badge titles")
    # Sprint 2C: discover registration destinations first (no PII), then
    # Google Forms schema enrichment so newly found forms.gle links get fields.
    try:
        from reg_discover import enrich_registration_discovery
        dstats = enrich_registration_discovery(events)
        log(f"Registration discovery: {dstats}")
    except Exception as ex:
        log(f"Registration discovery skipped: {type(ex).__name__}: {ex}")
    try:
        from gforms import enrich_google_forms_registration
        gstats = enrich_google_forms_registration(events)
        log(f"Google Forms enrichment: {gstats}")
    except Exception as ex:
        log(f"Google Forms enrichment skipped: {type(ex).__name__}: {ex}")
    backfill_hrs_from_time(events)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now(HKT).isoformat(timespec="minutes"), "status": status, "events": events}, f, ensure_ascii=False, indent=1)
    log("\n========== SUMMARY ==========")
    for s in status:
        log(f"{s.get('status','?')} {s['source']}: n={s.get('n',0)} via {s.get('method','')} raw={s.get('raw_candidates','-')}")
    log(f"Total events: {len(events)}")

if __name__ == "__main__":
    main()
